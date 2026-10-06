"""Go-Explore search for an input plan that reaches a goal in a stage.

An archive maps cells (player position and the goal's score) to compressed save states; each
iteration restores a rarely chosen cell and plays random 16-frame macros (the stage's
plan.HEADINGS set) from it. A rollout wins when the goal is reached (GOALS: the stage cleared, a
clear without a Wumpa, the Wumpa count wrapping at 100, a third Aku Aku mask); a death, a level
change that is not the clear (a bonus round), or a move the goal forbids ends it. A goal that
farms also plays QUIT_MOVE now and then: stand, quit from the pause menu and enter the stage
again, which commits the player's Wumpa and masks and brings the stage's items back, as a player
farming them would. The winning plan starts from a derivable state (the stage's start, or
`--from`), so it replays on any checkout running the core build it records (a quit is kept as the
inputs it took).
Progress is logged every LOG_EVERY iterations, with a screenshot of the best cell (highest score,
then deepest).

    python tools/achievement-harness/explore.py STAGE [--goal G] [--from STATE] [--out PLAN]
        [--minutes M] [--seed N]
"""

import argparse
import random
import sys
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import achievements
import navigation
import plan as plans
import states
from harness import SECONDS_PER_MINUTE, Emu, mask_of
from probes import (
    DISPLAY_FLAGS_NORMAL,
    GAME_STATE,
    GAME_STATE_STAGE_CLEARED,
    LEVEL_ID,
    LID_STAGE_CLEAR,
    NEXT_DISPLAY_FLAGS,
    PLAYER_POINTER,
    PLAYER_POSITION_OFFSETS,
    RESPAWN_COUNT,
    aku_level,
    player_fruit,
)
from provision import SHOTS_DIR

CELL_SHIFT = 19
ROLLOUT_SEGMENTS = 40
REPEAT_PROBABILITY = 0.7
DEATH_CONFIRM_FRAMES = 300
MAX_CELLS_WITH_STATE = 700
DEFAULT_ITERATIONS = 20000
DEFAULT_MINUTES = 45
DEFAULT_SEED = 1
LOG_EVERY = 50
ITERATION_DIGITS = 5
COMPRESSION_LEVEL = 1
POSITION_BYTES = 4
SIGN_BIT = 1 << 31
WORD_RANGE = 1 << 32
SELECTION_EXPONENT = 0.5
# Share of rollouts started from the FRONTIER_CELLS deepest cells: a hard obstacle (a boulder
# chase, a timed jump) is only passed from the frontier, which uniform picking rarely revisits.
FRONTIER_PROBABILITY = 0.5
FRONTIER_CELLS = 5
DEAD = "dead"
CLEARED = "cleared"
ELSEWHERE = "elsewhere"
REACHED = "reached"
FORBIDDEN = "forbidden"
STUCK = "stuck"  # a quit that never reached the map (SELECT ignored mid-air)
QUIT_MOVE = "quit-and-reenter"
QUIT_PROBABILITY = 0.02  # per segment: a quit costs about a thousand frames of menus and loading
CLEAR_GOAL = "clear"
AKU_INVINCIBLE_LEVEL = achievements.collectible_seed().AKU_INVINCIBLE_LEVEL


@dataclass(frozen=True)
class Goal:
    about: str
    score: Callable  # Runner -> int; a cell key, and the frontier favours the highest
    check: Callable  # Runner -> REACHED, FORBIDDEN or None, after every frame
    clear_wins: bool  # the stage's clear is the goal; otherwise it ends the rollout
    farms: bool = False  # QUIT_MOVE is played: the goal's items come back on re-entry


def no_score(_runner):
    return 0


def nothing_to_check(_runner):
    return None


def fruit_score(runner):
    return runner.fruit or 0


def fruit_wrapped(runner):
    """The player's Wumpa count went down: it passed 100 and became an extra life."""
    if runner.fruit is not None and runner.previous_fruit is not None:
        if runner.fruit < runner.previous_fruit:
            return REACHED
        return None
    return None


def fruit_collected(runner):
    if runner.fruit is not None and runner.fruit != runner.start_fruit:
        return FORBIDDEN
    return None


def aku_score(runner):
    return aku_level(runner.emu) or 0


def aku_invincible(runner):
    return REACHED if aku_score(runner) >= AKU_INVINCIBLE_LEVEL else None


GOALS = {
    CLEAR_GOAL: Goal("clear the stage", no_score, nothing_to_check, clear_wins=True),
    "no-wumpa": Goal(
        "clear the stage without collecting a Wumpa", no_score, fruit_collected, clear_wins=True
    ),
    "wumpa": Goal(
        "wrap the Wumpa count at 100", fruit_score, fruit_wrapped, clear_wins=False, farms=True
    ),
    "aku": Goal(
        "hold three Aku Aku masks", aku_score, aku_invincible, clear_wins=False, farms=True
    ),
}


def runs_of(masks):
    """Per-frame button masks -> [[frames, button_mask], ...], a run per unchanged mask."""
    runs = []
    for mask in masks:
        if runs and runs[-1][1] == mask:
            runs[-1][0] += 1
        else:
            runs.append([1, mask])
    return runs


class Runner:
    """Plays frames in a stage and reports a death, the clear, another level loading, or what the
    goal checks."""

    def __init__(self, emu, goal):
        self.emu = emu
        self.goal = goal
        self.respawns = emu.s32(RESPAWN_COUNT)
        self.level_id = emu.u8(LEVEL_ID)
        self.start_fruit = player_fruit(emu)
        self.fruit = self.previous_fruit = self.start_fruit

    def sync(self):
        """After a restore: the counters the goal compares frame to frame restart from here."""
        self.fruit = self.previous_fruit = player_fruit(self.emu)

    def position(self):
        coordinates = []
        for offset in PLAYER_POSITION_OFFSETS:
            value = self.emu.deref(PLAYER_POINTER, offset, size=POSITION_BYTES) or 0
            coordinates.append(value - WORD_RANGE if value & SIGN_BIT else value)
        return coordinates

    def outcome(self):
        """CLEARED, DEAD (respawned), ELSEWHERE (another level loaded), the goal's REACHED or
        FORBIDDEN, or None."""
        level_id = self.emu.u8(LEVEL_ID)
        if self.emu.u32(GAME_STATE) == GAME_STATE_STAGE_CLEARED or level_id == LID_STAGE_CLEAR:
            return CLEARED
        if self.emu.s32(RESPAWN_COUNT) != self.respawns:
            return DEAD
        if level_id != self.level_id:
            return ELSEWHERE
        return self.goal.check(self)

    def frame(self, mask):
        """Runs one frame; the outcome, or DEAD on the death camera's first frame."""
        self.emu.run(1, mask)
        self.previous_fruit, self.fruit = self.fruit, player_fruit(self.emu)
        outcome = self.outcome()
        if outcome is None and self.emu.u32(NEXT_DISPLAY_FLAGS) != DISPLAY_FLAGS_NORMAL:
            return DEAD
        return outcome

    def run_macro(self, macro):
        for frames, buttons in macro:
            mask = mask_of(buttons)
            for _ in range(frames):
                outcome = self.frame(mask)
                if outcome:
                    return outcome
        return None

    def confirm(self):
        """After the death camera flag moves: waits to tell a respawn from the stage ending."""
        for _ in range(DEATH_CONFIRM_FRAMES):
            self.emu.run(1, 0)
            outcome = self.outcome()
            if outcome in (CLEARED, DEAD, ELSEWHERE):
                return outcome
            else:
                pass  # The goal's own checks do not count on the way to a respawn.
        return DEAD

    def won(self, outcome):
        return outcome == REACHED or (outcome == CLEARED and self.goal.clear_wins)

    def quit_and_reenter(self):
        """Stands, quits from the pause menu and enters the stage again from the map.

        Returns the outcome (None once back in control of the same stage) and the inputs every
        frame took, recorded so the plan replays them.
        """
        masks = []

        def record(emu):
            masks.append(emu.buttons)

        self.emu.frame_hooks.append(record)
        try:
            outcome = self.run_macro([(navigation.QUIT_STAND_FRAMES, [])])
            if outcome is None:
                navigation.pause_and_quit(self.emu)
                entered = navigation.enter_stage(self.emu)
                outcome = None if entered == self.level_id else ELSEWHERE
            else:
                pass  # Died or reached the goal while standing.
        except TimeoutError:
            outcome = STUCK
        finally:
            self.emu.frame_hooks.remove(record)
        self.respawns = self.emu.s32(RESPAWN_COUNT)  # the map resets the count
        self.sync()
        return outcome, runs_of(masks)


class Explorer:
    def __init__(self, emu, goal, seed, macro_names, shot_dir):
        self.emu = emu
        self.runner = Runner(emu, goal)
        self.rng = random.Random(seed)
        self.macro_names = macro_names
        self.shot_dir = shot_dir
        self.moves = [*macro_names, QUIT_MOVE] if goal.farms else list(macro_names)
        self.archive = {}
        self._store(self._cell(), b"", ())

    def _cell(self):
        """Position cell, then the goal's score: a higher score is a new cell at any position."""
        position = tuple(coordinate >> CELL_SHIFT for coordinate in self.runner.position())
        return (*position, self.runner.goal.score(self.runner))

    def _rank(self, cell):
        """Frontier order: the goal's score (the cell key's last field), then the plan's depth."""
        return (cell[-1], len(self.archive[cell]["plan"]))

    def _store(self, cell, plan, quits):
        """`plan`: indices into `moves`; `quits`: the recorded inputs of each QUIT_MOVE in it."""
        entry = self.archive.get(cell)
        if entry and len(entry["plan"]) <= len(plan):
            entry["seen"] += 1
            return
        state = zlib.compress(self.emu.snapshot(), COMPRESSION_LEVEL)
        chosen = entry["chosen"] if entry else 0
        seen = entry["seen"] + 1 if entry else 0
        self.archive[cell] = {
            "state": state,
            "plan": plan,
            "quits": quits,
            "chosen": chosen,
            "seen": seen,
        }
        if len(self.archive) > MAX_CELLS_WITH_STATE:
            # TRADEOFF: evicts the most-chosen cell outright; a disk-backed archive keeps them all.
            worst = max(self.archive, key=lambda c: self.archive[c]["chosen"])
            del self.archive[worst]

    def _pick(self):
        cells = list(self.archive)
        if self.rng.random() < FRONTIER_PROBABILITY:
            cells.sort(key=self._rank, reverse=True)
            cells = cells[:FRONTIER_CELLS]
        else:
            pass  # Any cell, the rarely chosen and rarely seen ones first.
        weights = [
            (1 + self.archive[c]["chosen"]) ** -SELECTION_EXPONENT
            + (1 + self.archive[c]["seen"]) ** -SELECTION_EXPONENT
            for c in cells
        ]
        return self.rng.choices(cells, weights)[0]

    def rollout(self, cell):
        """Random moves from `cell`; returns the winning `(plan, quits)`, or None."""
        entry = self.archive[cell]
        entry["chosen"] += 1
        self.emu.restore(zlib.decompress(entry["state"]))
        self.runner.sync()
        self.runner.respawns = self.emu.s32(RESPAWN_COUNT)
        plan = bytearray(entry["plan"])
        quits = entry["quits"]
        macro = self.rng.randrange(len(self.macro_names))
        for _ in range(ROLLOUT_SEGMENTS):
            if self.runner.goal.farms and self.rng.random() < QUIT_PROBABILITY:
                plan.append(self.moves.index(QUIT_MOVE))
                outcome, inputs = self.runner.quit_and_reenter()
                quits = (*quits, inputs)
            else:
                if self.rng.random() > REPEAT_PROBABILITY:
                    macro = self.rng.randrange(len(self.macro_names))
                else:
                    pass  # The previous macro plays again.
                plan.append(macro)
                outcome = self.runner.run_macro(plans.MACROS[self.macro_names[macro]])
            if outcome == DEAD:
                outcome = self.runner.confirm()
            if outcome is None:
                self._store(self._cell(), bytes(plan), quits)
            elif self.runner.won(outcome):
                return bytes(plan), quits
            elif outcome in (DEAD, ELSEWHERE, FORBIDDEN, CLEARED, STUCK):
                return None
            else:
                raise ValueError(f"unknown rollout outcome {outcome!r}")
        return None

    def run(self, iterations, seconds):
        """Rollouts until one reaches the goal (`(plan, quits)`), or None when out of budget."""
        started = time.time()
        for iteration in range(iterations):
            won = self.rollout(self._pick())
            if won is not None:
                plan, quits = won
                print(
                    f"{self.runner.goal.about}: reached at iteration {iteration}, "
                    f"{len(plan)} moves, {len(quits)} quits",
                    flush=True,
                )
                return won
            elapsed = time.time() - started
            if iteration % LOG_EVERY == 0:
                self._report(iteration, elapsed)
            if elapsed > seconds:
                print(f"time box of {seconds:.0f}s spent at iteration {iteration}", flush=True)
                return None
        return None

    def deepest(self):
        """The best archived cell: the highest score, then the longest plan (the furthest the
        search got alive)."""
        return max(self.archive, key=self._rank)

    def inputs(self, plan, quits):
        """A plan's moves -> its names and its `[frames, button_mask]` inputs."""
        names, inputs = [], []
        recorded = iter(quits)
        for index in plan:
            name = self.moves[index]
            names.append(name)
            if name == QUIT_MOVE:
                inputs.extend(next(recorded))
            else:
                inputs.extend(plans.expand([name]))
        return names, inputs

    def _report(self, iteration, elapsed):
        deepest = self.deepest()
        entry = self.archive[deepest]
        print(
            f"it {iteration} cells {len(self.archive)} best score {deepest[-1]} "
            f"depth {len(entry['plan'])} quits {len(entry['quits'])} t={elapsed:.0f}s",
            flush=True,
        )
        self.emu.restore(zlib.decompress(self.archive[deepest]["state"]))
        self.emu.run(1, 0)
        self.emu.screenshot(self.shot_dir / f"it{iteration:0{ITERATION_DIGITS}d}.png")


def main():
    stages = {stage.name: stage for stage in states.STAGES}
    parser = argparse.ArgumentParser(description="Search an input plan that reaches a goal.")
    parser.add_argument("stage", choices=sorted(stages))
    parser.add_argument("--goal", default=CLEAR_GOAL, choices=sorted(GOALS))
    parser.add_argument(
        "--from",
        dest="start",
        choices=sorted(states.RECIPES),
        help="derivable state inside the stage to search from (default: the stage's start)",
    )
    parser.add_argument("--out", help="plan to write (default: the stage's plan for the goal)")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--minutes", type=float, default=DEFAULT_MINUTES, help="wall-clock box")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    stage = stages[args.stage]
    start = args.start or stage.start
    emu = Emu().load()
    states.load(emu, start)
    macro_names = plans.HEADINGS[stage.heading]
    shot_dir = SHOTS_DIR / "explore" / f"{stage.name}-{args.goal}"
    explorer = Explorer(emu, GOALS[args.goal], args.seed, macro_names, shot_dir)
    won = explorer.run(args.iterations, args.minutes * SECONDS_PER_MINUTE)
    out = Path(args.out) if args.out else stage.goal_plan_path(args.goal)
    if won is not None:
        best, quits = won
    elif args.goal == CLEAR_GOAL:
        # A failed search keeps its deepest alive route, a place mid-stage to die at.
        best, quits = explorer.archive[explorer.deepest()]["plan"], ()
        out = out.with_name(stage.deepest_plan_path.name)
    else:
        print(f"{GOALS[args.goal].about}: not reached; no plan written", flush=True)
        return 1
    names, inputs = explorer.inputs(best, quits)
    plan = plans.Plan(
        start=start,
        core=emu.core_name,
        core_version=emu.core_version,
        done=won is not None,
        macros=names,
        inputs=inputs,
    )
    print(f"plan written to {plans.save(plan, out)}; done={plan.done}", flush=True)
    return 0 if plan.done else 1


if __name__ == "__main__":
    sys.exit(main())
