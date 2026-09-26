"""Named save states, each derived from a cold boot by scripted navigation and cached per core.

No state is hand-made: `load(emu, name)` restores it from `.cache/achievement-harness/states/`
(one directory per core build) or derives it from its parent recipe, down to a cold boot, so every
scenario and every input plan replays on a fresh checkout. Pass `fresh=True` (or delete the cache)
after changing a recipe or navigation.py.

    python tools/achievement-harness/states.py [--core CORE] [--fresh] [NAME ...]
"""

import argparse
import hashlib
from collections.abc import Callable
from dataclasses import dataclass

import navigation
import plan as plans
from harness import CORE_DEFAULTS, DEFAULT_CORE, SHORT_HASH_CHARS, Emu
from probes import LID_NSANITY_BEACH
from provision import PLANS_DIR, STATES_DIR

NSANITY_BEACH_CLEAR_PLAN = PLANS_DIR / "nsanity-beach-clear.json"
STAGE_CLEAR_SETTLE_FRAMES = 60
NAME_COLUMN_WIDTH = 24

_derived_this_process = set()


@dataclass(frozen=True)
class Recipe:
    parent: str | None  # None: derived from a cold boot
    derive: Callable
    about: str


def _enter_nsanity_beach(emu):
    entered = navigation.enter_stage(emu)
    if entered != LID_NSANITY_BEACH:
        raise RuntimeError(
            f"expected N. Sanity Beach (lid {LID_NSANITY_BEACH:#x}), got {entered:#x}"
        )


def _clear_nsanity_beach(emu):
    plan = plans.load(NSANITY_BEACH_CLEAR_PLAN)
    if plan.start != RECIPES["nsanity-beach-clear"].parent:
        raise RuntimeError(f"{NSANITY_BEACH_CLEAR_PLAN.name} starts from {plan.start}")
    plans.replay(emu, plan)
    navigation.wait_for_stage_clear(emu, NSANITY_BEACH_CLEAR_PLAN.name)
    emu.step(STAGE_CLEAR_SETTLE_FRAMES)


RECIPES = {
    "map": Recipe(None, navigation.boot_to_map, "island map after NEW GAME, on N. Sanity Beach"),
    "nsanity-beach-start": Recipe(
        "map", _enter_nsanity_beach, "N. Sanity Beach, just after the player gains control"
    ),
    "nsanity-beach-clear": Recipe(
        "nsanity-beach-start",
        _clear_nsanity_beach,
        "Stage Clear screen after plans/nsanity-beach-clear.json clears N. Sanity Beach",
    ),
}


def build_dir(emu):
    """States of one core build: another build may not load them, let alone replay them."""
    build = "".join(c if c.isalnum() else "-" for c in emu.core_version)
    return STATES_DIR / emu.core_name / build


def load(emu, name, fresh=False):
    """Restores state `name` on `emu`, deriving it (and its parents) first when not cached.

    `fresh` re-derives every state of the chain not yet derived by this process. A derived
    state is saved and then loaded back, so a run continues from the same restored emulation
    whether the state came from the cache or was derived moments ago.
    """
    if name not in RECIPES:
        raise ValueError(f"unknown state {name!r}; derivable states: {sorted(RECIPES)}")
    target = build_dir(emu) / f"{name}.state"
    if target.is_file() and (not fresh or name in _derived_this_process):
        emu.load_state(target)
        return target
    recipe = RECIPES[name]
    if recipe.parent is not None:
        load(emu, recipe.parent, fresh)
    elif not emu.pristine:
        raise RuntimeError(f"{name} derives from a cold boot: load it on a fresh emulator")
    else:
        pass  # A freshly booted emulator is the cold-boot parent.
    recipe.derive(emu)
    emu.save_state(target)
    emu.load_state(target)
    _derived_this_process.add(name)
    return target


def digest(target):
    return hashlib.sha256(target.read_bytes()).hexdigest()[:SHORT_HASH_CHARS]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Derive (or re-derive) named states.")
    parser.add_argument("names", nargs="*", default=list(RECIPES), metavar="NAME")
    parser.add_argument("--core", default=DEFAULT_CORE, choices=sorted(CORE_DEFAULTS))
    parser.add_argument("--fresh", action="store_true", help="ignore cached states")
    args = parser.parse_args()
    emu = Emu(core=args.core).load()
    print(f"{emu.core_version}, rcheevos {emu.rcheevos_version}")
    for state_name in args.names:
        derived = load(emu, state_name, fresh=args.fresh)
        print(
            f"{state_name:{NAME_COLUMN_WIDTH}} {digest(derived)}  {RECIPES[state_name].about}",
            flush=True,
        )
