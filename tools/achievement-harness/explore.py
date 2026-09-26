"""Go-Explore search for an input plan that leaves a stage alive (i.e. clears it).

An archive maps position cells to compressed save states; each iteration restores a rarely chosen
cell and plays random 16-frame macros (plan.MACROS) from it. The winning plan starts from a named,
derivable state, so it replays on any checkout running the core build it records. Progress is
logged every LOG_EVERY iterations, with a screenshot of the deepest cell.

    python tools/achievement-harness/explore.py START_STATE OUT_PLAN [--iterations N] [--seed N]
"""

import argparse
import random
import sys
import time
import zlib

import plan as plans
import states
from harness import Emu, mask_of
from probes import (
    DISPLAY_FLAGS_NORMAL,
    GAME_STATE,
    GAME_STATE_CUTSCENE,
    GAME_STATE_PLAYING,
    LEVEL_ID,
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
DEFAULT_SEED = 1
LOG_EVERY = 50
ITERATION_DIGITS = 5
COMPRESSION_LEVEL = 1
POSITION_BYTES = 4
SIGN_BIT = 1 << 31
WORD_RANGE = 1 << 32
SELECTION_EXPONENT = 0.5
DEAD = "dead"
LEFT = "left"
MACRO_NAMES = list(plans.MACROS)


class Runner:
    """Plays frames in a stage and reports a death or the stage being left."""

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

    def frame(self, mask):
        """Runs one frame; returns DEAD (death camera or respawn), LEFT or None."""
        self.emu.run(1, mask)
        died = self.emu.s32(RESPAWN_COUNT) != self.respawns
        if died or self.emu.u32(NEXT_DISPLAY_FLAGS) != DISPLAY_FLAGS_NORMAL:
            return DEAD
        if self.emu.u8(LEVEL_ID) != self.level_id or not self.playing():
            return LEFT
        return None

    def playing(self):
        return self.emu.u32(GAME_STATE) == GAME_STATE_PLAYING

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
            if self.emu.s32(RESPAWN_COUNT) != self.respawns:
                return DEAD
            left_level = self.emu.u8(LEVEL_ID) != self.level_id
            game_state = self.emu.u32(GAME_STATE)
            if left_level or game_state not in (GAME_STATE_PLAYING, GAME_STATE_CUTSCENE):
                return LEFT
        return DEAD


class Explorer:
    def __init__(self, emu, seed):
        self.emu = emu
        self.runner = Runner(emu)
        self.rng = random.Random(seed)
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
        macro = self.rng.randrange(len(MACRO_NAMES))
        for _ in range(ROLLOUT_SEGMENTS):
            if self.rng.random() > REPEAT_PROBABILITY:
                macro = self.rng.randrange(len(MACRO_NAMES))
            plan.append(macro)
            outcome = self.runner.run_macro(plans.MACROS[MACRO_NAMES[macro]])
            if outcome == DEAD:
                outcome = self.runner.confirm()
            if outcome == LEFT:
                return bytes(plan)
            if outcome == DEAD:
                return None
            self._store(self._cell(), bytes(plan))
        return None

    def run(self, iterations):
        started = time.time()
        for iteration in range(iterations):
            won = self.rollout(self._pick())
            if won is not None:
                print(f"stage left alive at iteration {iteration}, {len(won)} segments", flush=True)
                return won
            if iteration % LOG_EVERY == 0:
                self._report(iteration, time.time() - started)
        return None

    def _report(self, iteration, elapsed):
        deepest = max(self.archive, key=lambda c: len(self.archive[c]["plan"]))
        depth = len(self.archive[deepest]["plan"])
        print(
            f"it {iteration} cells {len(self.archive)} deepest {depth} t={elapsed:.0f}s",
            flush=True,
        )
        self.emu.restore(zlib.decompress(self.archive[deepest]["state"]))
        self.emu.run(1, 0)
        self.emu.screenshot(SHOTS_DIR / "explore" / f"it{iteration:0{ITERATION_DIGITS}d}.png")


def main():
    parser = argparse.ArgumentParser(description="Search an input plan that clears a stage.")
    parser.add_argument("start", choices=sorted(states.RECIPES), help="derivable start state")
    parser.add_argument("out", help="plan file to write (JSON)")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    emu = Emu().load()
    states.load(emu, args.start)
    won = Explorer(emu, args.seed).run(args.iterations)
    names = [MACRO_NAMES[index] for index in won] if won else []
    plan = plans.Plan(
        start=args.start,
        core=emu.core_name,
        core_version=emu.core_version,
        done=won is not None,
        macros=names,
        inputs=plans.expand(names),
    )
    print(f"plan written to {plans.save(plan, args.out)}; done={plan.done}", flush=True)
    return 0 if plan.done else 1


if __name__ == "__main__":
    sys.exit(main())
