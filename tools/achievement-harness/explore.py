"""Go-Explore search for an input plan that clears a stage.

An archive maps position cells to compressed save states; each iteration restores a rarely chosen
cell and plays random 16-frame macros (the stage's plan.HEADINGS set) from it. A rollout wins when
the game reports the stage cleared; a death, or a level change that is not the clear (a bonus
round), ends it. The winning plan starts from the stage's derivable start state, so it replays on
any checkout running the core build it records. Progress is logged every LOG_EVERY iterations,
with a screenshot of the deepest cell.

    python tools/achievement-harness/explore.py STAGE [--out PLAN] [--minutes M] [--seed N]
"""

import argparse
import random
import sys
import time
import zlib
from pathlib import Path

import plan as plans
import states
from harness import Emu, mask_of
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
)
from provision import SHOTS_DIR

CELL_SHIFT = 19
ROLLOUT_SEGMENTS = 40
REPEAT_PROBABILITY = 0.7
DEATH_CONFIRM_FRAMES = 300
MAX_CELLS_WITH_STATE = 700
DEFAULT_ITERATIONS = 20000
DEFAULT_MINUTES = 45
SECONDS_PER_MINUTE = 60
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


class Runner:
    """Plays frames in a stage and reports a death, the clear, or another level loading."""

    def __init__(self, emu):
        self.emu = emu
        self.respawns = emu.s32(RESPAWN_COUNT)
        self.level_id = emu.u8(LEVEL_ID)

    def position(self):
        coordinates = []
        for offset in PLAYER_POSITION_OFFSETS:
            value = self.emu.deref(PLAYER_POINTER, offset, size=POSITION_BYTES) or 0
            coordinates.append(value - WORD_RANGE if value & SIGN_BIT else value)
        return coordinates

    def outcome(self):
        """CLEARED, DEAD (respawned), ELSEWHERE (another level loaded) or None."""
        level_id = self.emu.u8(LEVEL_ID)
        if self.emu.u32(GAME_STATE) == GAME_STATE_STAGE_CLEARED or level_id == LID_STAGE_CLEAR:
            return CLEARED
        if self.emu.s32(RESPAWN_COUNT) != self.respawns:
            return DEAD
        if level_id != self.level_id:
            return ELSEWHERE
        return None

    def frame(self, mask):
        """Runs one frame; the outcome, or DEAD on the death camera's first frame."""
        self.emu.run(1, mask)
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
            if outcome is not None:
                return outcome
        return DEAD


class Explorer:
    def __init__(self, emu, seed, macro_names, shot_dir):
        self.emu = emu
        self.runner = Runner(emu)
        self.rng = random.Random(seed)
        self.macro_names = macro_names
        self.shot_dir = shot_dir
        self.archive = {}
        self._store(self._cell(), b"")

    def _cell(self):
        return tuple(coordinate >> CELL_SHIFT for coordinate in self.runner.position())

    def _store(self, cell, plan):
        entry = self.archive.get(cell)
        if entry and len(entry["plan"]) <= len(plan):
            entry["seen"] += 1
            return
        state = zlib.compress(self.emu.snapshot(), COMPRESSION_LEVEL)
        chosen = entry["chosen"] if entry else 0
        seen = entry["seen"] + 1 if entry else 0
        self.archive[cell] = {"state": state, "plan": plan, "chosen": chosen, "seen": seen}
        if len(self.archive) > MAX_CELLS_WITH_STATE:
            # TRADEOFF: evicts the most-chosen cell outright; a disk-backed archive keeps them all.
            worst = max(self.archive, key=lambda c: self.archive[c]["chosen"])
            del self.archive[worst]

    def _pick(self):
        cells = list(self.archive)
        if self.rng.random() < FRONTIER_PROBABILITY:
            cells.sort(key=lambda c: len(self.archive[c]["plan"]), reverse=True)
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
        """Random macros from `cell`; returns the winning macro indices, or None."""
        entry = self.archive[cell]
        entry["chosen"] += 1
        self.emu.restore(zlib.decompress(entry["state"]))
        plan = bytearray(entry["plan"])
        macro = self.rng.randrange(len(self.macro_names))
        for _ in range(ROLLOUT_SEGMENTS):
            if self.rng.random() > REPEAT_PROBABILITY:
                macro = self.rng.randrange(len(self.macro_names))
            plan.append(macro)
            outcome = self.runner.run_macro(plans.MACROS[self.macro_names[macro]])
            if outcome == DEAD:
                outcome = self.runner.confirm()
            if outcome is None:
                self._store(self._cell(), bytes(plan))
            elif outcome == CLEARED:
                return bytes(plan)
            elif outcome in (DEAD, ELSEWHERE):
                return None
            else:
                raise ValueError(f"unknown rollout outcome {outcome!r}")
        return None

    def run(self, iterations, seconds):
        """Rollouts until one clears the stage (its macro indices), or None when out of budget."""
        started = time.time()
        for iteration in range(iterations):
            won = self.rollout(self._pick())
            if won is not None:
                print(f"stage cleared at iteration {iteration}, {len(won)} segments", flush=True)
                return won
            elapsed = time.time() - started
            if iteration % LOG_EVERY == 0:
                self._report(iteration, elapsed)
            if elapsed > seconds:
                print(f"time box of {seconds:.0f}s spent at iteration {iteration}", flush=True)
                return None
        return None

    def deepest(self):
        """The archived cell with the longest plan: the furthest the search got alive."""
        return max(self.archive, key=lambda c: len(self.archive[c]["plan"]))

    def _report(self, iteration, elapsed):
        deepest = self.deepest()
        depth = len(self.archive[deepest]["plan"])
        print(
            f"it {iteration} cells {len(self.archive)} deepest {depth} t={elapsed:.0f}s",
            flush=True,
        )
        self.emu.restore(zlib.decompress(self.archive[deepest]["state"]))
        self.emu.run(1, 0)
        self.emu.screenshot(self.shot_dir / f"it{iteration:0{ITERATION_DIGITS}d}.png")


def main():
    stages = {stage.name: stage for stage in states.STAGES}
    parser = argparse.ArgumentParser(description="Search an input plan that clears a stage.")
    parser.add_argument("stage", choices=sorted(stages))
    parser.add_argument("--out", help="clearing plan to write (default: the stage's plan path)")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--minutes", type=float, default=DEFAULT_MINUTES, help="wall-clock box")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    stage = stages[args.stage]
    emu = Emu().load()
    states.load(emu, stage.start)
    macro_names = plans.HEADINGS[stage.heading]
    explorer = Explorer(emu, args.seed, macro_names, SHOTS_DIR / "explore" / stage.name)
    won = explorer.run(args.iterations, args.minutes * SECONDS_PER_MINUTE)
    out = Path(args.out) if args.out else stage.plan_path
    if won is None:
        # A failed search keeps its deepest alive route, a place mid-stage to die at.
        deepest = explorer.archive[explorer.deepest()]["plan"]
        out = out.with_name(stage.deepest_plan_path.name)
    else:
        deepest = won
    names = [macro_names[index] for index in deepest]
    plan = plans.Plan(
        start=stage.start,
        core=emu.core_name,
        core_version=emu.core_version,
        done=won is not None,
        macros=names,
        inputs=plans.expand(names),
    )
    print(f"plan written to {plans.save(plan, out)}; done={plan.done}", flush=True)
    return 0 if plan.done else 1


if __name__ == "__main__":
    sys.exit(main())
