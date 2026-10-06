"""Named save states, each derived from a cold boot by scripted navigation and cached.

No state is hand-made: `load(emu, name)` restores it from `.cache/achievement-harness/states/` or
derives it from its parent recipe, down to a cold boot. The cache directory is named after the core
build and a digest of RECIPE_SOURCES, so a new core build or an edited recipe, navigation move or
plan derives afresh instead of reusing a state a fresh checkout could no longer derive.
`fresh=True` re-derives anyway.

    python tools/achievement-harness/states.py [--core CORE] [--fresh] [NAME ...]
"""

import argparse
import hashlib
from collections.abc import Callable
from dataclasses import dataclass

import navigation
import plan as plans
from harness import CORE_DEFAULTS, DEFAULT_CORE, SHORT_HASH_CHARS, Emu
from probes import (
    LEVELS_UNLOCKED,
    LID_BOULDERS,
    LID_JUNGLE_ROLLERS,
    LID_NSANITY_BEACH,
    LID_PAPU_PAPU,
    LID_ROLLING_STONES,
    LID_THE_GREAT_GATE,
    LID_UPSTREAM,
    aku_level,
    player_fruit,
)
from provision import HARNESS_DIR, PLANS_DIR, SHIM_SOURCE, STATES_DIR

STAGE_CLEAR_SETTLE_FRAMES = 60
NAME_COLUMN_WIDTH = 24
FIRST_MAP_INDEX = 0
# Map stages up to Rolling Stones (cursor 6), the last of the level achievements.
MAP_STAGES_UNLOCKED = 7
# Farming N. Sanity Beach: its clearing plan, replayed up to a point, then a quit and a re-entry,
# which commits what was collected and brings the crates back.
# The plan breaks the stage's first Aku Aku crate at frame 2229.
FIRST_MASK_ROUTE_FRAMES = 2320
FARMED_MASKS = 2
# The plan's 20th Wumpa lands at frame 6087; the second pass collects 16 of them.
WUMPA_ROUTE_FRAMES = 6100
WUMPA_FARM_PASSES = 2
FARMED_WUMPA = 36
# Longer than navigation.QUIT_STAND_FRAMES; the plans searched from the farmed states depend on it.
FARM_STAND_FRAMES = 120


@dataclass(frozen=True)
class Stage:
    name: str  # prefix of its states, plan and scenarios
    level_id: int  # c1 LID, what `0x6188D` reads inside the stage
    map_index: int  # map cursor (`0x619C5`) on the stage
    heading: str  # plan.HEADINGS key: the way the stage runs on screen

    @property
    def start(self):
        return f"{self.name}-start"

    @property
    def clear(self):
        return f"{self.name}-clear"

    @property
    def plan_path(self):
        return self.goal_plan_path("clear")

    def goal_plan_path(self, goal):
        """`plans/<stage>-<goal>.json`: a searched route to the goal (explore.GOALS)."""
        return PLANS_DIR / f"{self.name}-{goal}.json"

    @property
    def deepest_plan_path(self):
        """A failed search's furthest alive route (`done: false`), where deaths are played."""
        return PLANS_DIR / f"{self.name}-deepest.json"


STAGES = (
    Stage("nsanity-beach", LID_NSANITY_BEACH, 0, "up"),
    Stage("jungle-rollers", LID_JUNGLE_ROLLERS, 1, "up"),
    Stage("the-great-gate", LID_THE_GREAT_GATE, 2, "right"),
    Stage("boulders", LID_BOULDERS, 3, "down"),
    Stage("upstream", LID_UPSTREAM, 4, "up"),
    Stage("rolling-stones", LID_ROLLING_STONES, 6, "up"),
)
# Boss fights on the map path of STAGES, entered only to judge what they show and fire.
BOSS_FIGHTS = (Stage("papu-papu", LID_PAPU_PAPU, 5, "up"),)
# Every file that decides what a derived state holds, clearing plans included.
RECIPE_SOURCES = (
    HARNESS_DIR / "states.py",
    HARNESS_DIR / "navigation.py",
    HARNESS_DIR / "probes.py",
    HARNESS_DIR / "plan.py",
    HARNESS_DIR / "harness.py",
    SHIM_SOURCE,
    *sorted(PLANS_DIR.glob("*.json")),
)

_derived_this_process = set()


@dataclass(frozen=True)
class Recipe:
    parent: str | None  # None: derived from a cold boot
    derive: Callable
    about: str


def _unlock_map(emu):
    """Pokes the unlocked-stage count, then enters and quits a stage so the map reloads with it.

    The only RAM write the harness makes: it reaches a stage, and every clear is still played.
    """
    emu.write_u32(LEVELS_UNLOCKED, MAP_STAGES_UNLOCKED)
    navigation.enter_stage(emu)
    navigation.pause_and_quit(emu)


def _enter(stage):
    def derive(emu):
        navigation.move_cursor_to(emu, stage.map_index)
        entered = navigation.enter_stage(emu)
        if entered != stage.level_id:
            raise RuntimeError(f"expected {stage.name} (lid {stage.level_id:#x}), got {entered:#x}")

    return derive


def _clear(stage):
    def derive(emu):
        plan = plans.load(stage.plan_path)
        if plan.start != stage.start:
            raise RuntimeError(f"{stage.plan_path.name} starts from {plan.start}")
        plans.replay(emu, plan)
        navigation.wait_for_stage_clear(emu, stage.plan_path.name)
        emu.step(STAGE_CLEAR_SETTLE_FRAMES)

    return derive


def _stage_recipes(stage):
    """`<stage>-start` and, when its plan is committed, `<stage>-clear`.

    N. Sanity Beach is the first stage of a new game; the others are entered from `map-unlocked`.
    """
    parent = "map" if stage.map_index == FIRST_MAP_INDEX else "map-unlocked"
    recipes = {
        stage.start: Recipe(
            parent, _enter(stage), f"{stage.name}, just after the player gains control"
        )
    }
    if stage.plan_path.is_file():
        recipes[stage.clear] = Recipe(
            stage.start,
            _clear(stage),
            f"Stage Clear screen after plans/{stage.plan_path.name}",
        )
    else:
        pass  # No clearing plan: no clear state, no clear scenario.
    return recipes


def _farm(route_frames, passes, probe, expected, what):
    """`passes` times: the beach's clearing plan up to `route_frames`, a stand, a quit and a
    re-entry; then `probe` must read `expected`, or the replay diverged.

    Real play, as a player farming crates would: nothing is written to RAM.
    """

    def derive(emu):
        plan = plans.load(STAGES[FIRST_MAP_INDEX].plan_path)
        route, frames = [], 0
        for run in plan.inputs:
            if frames >= route_frames:
                break
            route.append(run)
            frames += run[0]
        for _ in range(passes):
            for run_frames, mask in route:
                emu.run(run_frames, mask)
            emu.step(FARM_STAND_FRAMES)
            navigation.pause_and_quit(emu)
            navigation.enter_stage(emu)
        if probe(emu) != expected:
            raise RuntimeError(f"expected {expected} {what} after farming, got {probe(emu)}")

    return derive


RECIPES = {
    "map": Recipe(None, navigation.boot_to_map, "island map after NEW GAME, on N. Sanity Beach"),
    "map-unlocked": Recipe(
        "map",
        _unlock_map,
        f"island map with {MAP_STAGES_UNLOCKED} stages unlocked by a RAM poke",
    ),
}
for _stage in (*STAGES, *BOSS_FIGHTS):
    RECIPES.update(_stage_recipes(_stage))
RECIPES["nsanity-beach-two-masks"] = Recipe(
    STAGES[FIRST_MAP_INDEX].start,
    _farm(FIRST_MASK_ROUTE_FRAMES, FARMED_MASKS, aku_level, FARMED_MASKS, "Aku Aku masks"),
    f"N. Sanity Beach re-entered with {FARMED_MASKS} Aku Aku masks farmed from its first crate",
)
RECIPES["nsanity-beach-farmed-wumpa"] = Recipe(
    STAGES[FIRST_MAP_INDEX].start,
    _farm(WUMPA_ROUTE_FRAMES, WUMPA_FARM_PASSES, player_fruit, FARMED_WUMPA, "Wumpa"),
    f"N. Sanity Beach re-entered with {FARMED_WUMPA} Wumpa farmed by its clearing route",
)


def build_dir(emu):
    """States of one core build: another build may not load them, let alone replay them."""
    build = "".join(c if c.isalnum() else "-" for c in emu.core_version)
    return STATES_DIR / emu.core_name / build


def recipes_dir(emu):
    """Derived states of one core build and one version of RECIPE_SOURCES."""
    sources = hashlib.sha256()
    for path in RECIPE_SOURCES:
        sources.update(path.read_bytes())
    return build_dir(emu) / f"recipes-{sources.hexdigest()[:SHORT_HASH_CHARS]}"


def load(emu, name, fresh=False):
    """Restores state `name` on `emu`, deriving it (and its parents) first when not cached.

    `fresh` re-derives every state of the chain not yet derived by this process. A derived
    state is saved and then loaded back, so a run continues from the same restored emulation
    whether the state came from the cache or was derived moments ago.
    """
    if name not in RECIPES:
        raise ValueError(f"unknown state {name!r}; derivable states: {sorted(RECIPES)}")
    target = recipes_dir(emu) / f"{name}.state"
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
