"""Input plans: button sequences searched by explore.py and replayed frame-exactly.

A plan starts from a named state (states.RECIPES, derivable from a cold boot) and replays only on
the emulation it was searched on, so it records its core and that core's build. The inputs are the
replay's source of truth; the macro names only make the plan readable.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from harness import Btn, mask_of

SEGMENT_FRAMES = 16
JUMP_HOLD_FRAMES = 10
SPIN_HOLD_FRAMES = 4

U, X, S, L, R, D = Btn.UP, Btn.CROSS, Btn.SQUARE, Btn.LEFT, Btn.RIGHT, Btn.DOWN
JUMP_TAIL_FRAMES = SEGMENT_FRAMES - JUMP_HOLD_FRAMES
SPIN_TAIL_FRAMES = SEGMENT_FRAMES - SPIN_HOLD_FRAMES

# Each macro fills one segment: [(frames, buttons), ...].
MACROS = {
    "up": [(SEGMENT_FRAMES, [U])],
    "up-jump": [(JUMP_HOLD_FRAMES, [U, X]), (JUMP_TAIL_FRAMES, [U])],
    "up-spin": [(SPIN_HOLD_FRAMES, [U, S]), (SPIN_TAIL_FRAMES, [U])],
    "jump": [(JUMP_HOLD_FRAMES, [X]), (JUMP_TAIL_FRAMES, [])],
    "spin": [(SPIN_HOLD_FRAMES, [S]), (SPIN_TAIL_FRAMES, [])],
    "up-left": [(SEGMENT_FRAMES, [U, L])],
    "up-right": [(SEGMENT_FRAMES, [U, R])],
    "left": [(SEGMENT_FRAMES, [L])],
    "right": [(SEGMENT_FRAMES, [R])],
    "up-left-jump": [(JUMP_HOLD_FRAMES, [U, L, X]), (JUMP_TAIL_FRAMES, [U, L])],
    "up-right-jump": [(JUMP_HOLD_FRAMES, [U, R, X]), (JUMP_TAIL_FRAMES, [U, R])],
    "wait": [(SEGMENT_FRAMES, [])],
    "back": [(SEGMENT_FRAMES, [D])],
}

REQUIRED_FIELDS = ("start", "core", "core_version", "done", "macros", "inputs")
INPUT_FIELDS = ("frames", "button_mask")


@dataclass
class Plan:
    start: str
    core: str
    core_version: str
    done: bool
    macros: list
    inputs: list

    @property
    def frames(self):
        return sum(frames for frames, _mask in self.inputs)


def expand(macro_names):
    """Macro names -> [[frames, button_mask], ...]."""
    inputs = []
    for name in macro_names:
        for frames, buttons in MACROS[name]:
            inputs.append([frames, mask_of(buttons)])
    return inputs


def _is_input(entry):
    if not isinstance(entry, list) or len(entry) != len(INPUT_FIELDS):
        return False
    frames, mask = entry
    return isinstance(frames, int) and isinstance(mask, int) and frames > 0 and mask >= 0


def load(path):
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} is not a plan: expected a JSON object")
    missing = [field for field in REQUIRED_FIELDS if field not in payload]
    if missing:
        raise ValueError(f"{path} is not a plan: missing {missing}")
    plan = Plan(**{field: payload[field] for field in REQUIRED_FIELDS})
    for entry in plan.inputs:
        if not _is_input(entry):
            raise ValueError(f"{path}: {entry!r} is not a [frames, button_mask] pair")
    return plan


def save(plan, path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(plan)) + "\n")
    return target


def replay(emu, plan):
    """Runs the plan's inputs; the caller has already loaded `plan.start` on `emu`."""
    if emu.core_name != plan.core:
        raise ValueError(f"the plan was searched on {plan.core}, not {emu.core_name}")
    if emu.core_version != plan.core_version:
        print(
            f"warning: plan searched on {plan.core_version}, running {emu.core_version}; "
            "a different core build may diverge",
            flush=True,
        )
    for frames, mask in plan.inputs:
        emu.run(frames, mask)
