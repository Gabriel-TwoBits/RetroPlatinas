"""Recorded scenarios: scripted play from a derivable state, judged against the repo's achievements.

Each scenario states which level achievements must trigger and the level (lid) the game must show
when they do (usually none: a death, a quit or the attract demo must never unlock anything), and
exits non-zero when a trigger is missing, repeated, unexpected or fires on another level.

    python tools/achievement-harness/scenarios.py [--core CORE] NAME [NAME ...] | all

A core and the rcheevos runtime are process-global, so several scenarios run one per process.
"""

import argparse
import random
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

import achievements
import navigation
import plan as plans
from harness import CORE_DEFAULTS, DEFAULT_CORE, FRAMES_PER_SECOND, SECONDS_PER_MINUTE, Btn
from probes import (
    FIXED_POINT_SHIFT,
    GAME_STATE,
    GAME_STATE_GAME_OVER,
    GAME_STATE_PLAYING,
    LID_STAGE_CLEAR,
    LID_TITLE,
    RESPAWN_COUNT,
)
from session import Session
from states import STAGES

COLD_BOOT_FRAMES = 3 * SECONDS_PER_MINUTE * FRAMES_PER_SECOND
COLD_BOOT_SHOT_FRAMES = 10 * FRAMES_PER_SECOND
ATTRACT_FRAMES = 15 * SECONDS_PER_MINUTE * FRAMES_PER_SECOND
ATTRACT_SHOT_FRAMES = 30 * FRAMES_PER_SECOND
LEAVE_SPAWN_ZONE_FRAMES = 150
STAND_BEFORE_QUIT_FRAMES = 400
DEATH_TIMEOUT_FRAMES = 4 * SECONDS_PER_MINUTE * FRAMES_PER_SECOND
AFTER_DEATH_FRAMES = 300
IDLE_IN_SPAWN_ZONE_FRAMES = 600
QUIT_AFTER_CONTROL_FRAMES = 60
AFTER_LAST_QUIT_FRAMES = 600
AFTER_GAME_OVER_FRAMES = 1200
# Four lives at a new game; extra lives picked up on the way are bounded by this.
MAX_DEATHS_TO_GAME_OVER = 12
STAGE_CLEAR_SHOTS = 5
STAGE_CLEAR_SHOT_FRAMES = 60
DEATH_SEED = 1
PLAN_PREFIX_DIVISOR = 2  # deaths start halfway through a stage's clearing plan

HEADING_BUTTONS = {"up": Btn.UP, "down": Btn.DOWN, "right": Btn.RIGHT}


@dataclass(frozen=True)
class Scenario:
    start: str | None  # a states.RECIPES name; None boots the disc
    expected: dict  # stage level id -> the lid the game shows when its achievement must trigger
    about: str
    play: Callable


def respawns(emu):
    return emu.s32(RESPAWN_COUNT) >> FIXED_POINT_SHIFT


def player_in_control(emu):
    return emu.u32(GAME_STATE) == GAME_STATE_PLAYING


def game_over(emu):
    return emu.u32(GAME_STATE) == GAME_STATE_GAME_OVER


def die(s, stage, rng, label, route):
    """Replays `route`, then random macros of the stage's heading, until a respawn or game over.

    Returns True on a respawn (the player is back in control), False on the game over.
    """
    before = respawns(s.emu)
    replayed = 0
    for frames, mask in route:
        if respawns(s.emu) != before or game_over(s.emu):
            break  # Off the route after a respawn: the rest would play into the menus.
        s.emu.run(frames, mask)
        replayed += frames
    names = plans.HEADINGS[stage.heading]
    played = 0
    while respawns(s.emu) == before and not game_over(s.emu):
        if played >= DEATH_TIMEOUT_FRAMES:
            raise TimeoutError(f"{label}: no death after {played} frames of random play")
        for frames, buttons in plans.MACROS[rng.choice(names)]:
            s.step(frames, buttons)
        played += plans.SEGMENT_FRAMES
    if game_over(s.emu):
        s.note(f"{label}: game over after {replayed} replayed and {played} random frames")
        return False
    s.note(
        f"{label}: respawn count {before} -> {respawns(s.emu)} "
        f"after {replayed} replayed and {played} random frames"
    )
    s.wait_until(player_in_control, navigation.LOAD_TIMEOUT_FRAMES, f"control after {label}")
    return True


def play_cold_boot(s):
    for _ in range(COLD_BOOT_FRAMES // COLD_BOOT_SHOT_FRAMES):
        s.step(COLD_BOOT_SHOT_FRAMES)
        s.shot("periodic")


def play_attract(s):
    for _ in range(ATTRACT_FRAMES // ATTRACT_SHOT_FRAMES):
        s.step(ATTRACT_SHOT_FRAMES)
        s.shot("periodic")


def death_route(s, stage):
    """The inputs replayed before each death, towards the middle of the stage.

    Searched plans never die, so they lead where random play meets hazards the start area may
    lack (The Great Gate).
    """
    if stage.plan_path.is_file():
        route = plans.load(stage.plan_path).inputs
        s.note(f"each death replays the first half of {stage.plan_path.name} first")
        return route[: len(route) // PLAN_PREFIX_DIVISOR]
    if stage.deepest_plan_path.is_file():
        s.note(f"each death replays {stage.deepest_plan_path.name} first")
        return plans.load(stage.deepest_plan_path).inputs
    s.note("no plan: the deaths happen around the start")
    return []


def deaths(stage):
    def play(s):
        rng = random.Random(DEATH_SEED)
        route = death_route(s, stage)
        die(s, stage, rng, "death 1", route)
        s.rearm("death 2: re-armed right after the respawn")
        die(s, stage, rng, "death 2", route)
        s.step(AFTER_DEATH_FRAMES)
        s.rearm("death 3: after idling where the player respawned")
        s.step(IDLE_IN_SPAWN_ZONE_FRAMES)
        die(s, stage, rng, "death 3", route)
        s.step(AFTER_DEATH_FRAMES)

    return play


def down_to_game_over(stage):
    def play(s):
        rng = random.Random(DEATH_SEED)
        route = death_route(s, stage)
        for death in range(1, MAX_DEATHS_TO_GAME_OVER + 1):
            if not die(s, stage, rng, f"death {death}", route):
                break
            s.rearm(f"death {death + 1}: dying on towards the game over")
        else:
            raise RuntimeError(f"no game over after {MAX_DEATHS_TO_GAME_OVER} deaths")
        s.wait_until(
            lambda e: navigation.level_id(e) == LID_TITLE,
            navigation.LOAD_TIMEOUT_FRAMES,
            "title level after the game over",
        )
        s.step(AFTER_GAME_OVER_FRAMES)
        s.shot("after-game-over")

    return play


def quits(stage):
    def play(s):
        s.note("A: quit right after gaining control")
        s.step(QUIT_AFTER_CONTROL_FRAMES)
        navigation.pause_and_quit(s.emu)

        # SELECT does not quit while Crash is still moving or falling (a pit ends the run in
        # Rolling Stones): standing lets any death respawn before the pause.
        s.rearm("B: re-enter, run out of the spawn zone, stand, quit")
        navigation.move_cursor_to(s.emu, stage.map_index)
        navigation.enter_stage(s.emu)
        s.step(LEAVE_SPAWN_ZONE_FRAMES, [HEADING_BUTTONS[stage.heading]])
        s.step(STAND_BEFORE_QUIT_FRAMES)
        s.wait_until(player_in_control, navigation.LOAD_TIMEOUT_FRAMES, "control before B's quit")
        navigation.pause_and_quit(s.emu)

        s.rearm("C: re-enter, stand still for a while, quit")
        navigation.move_cursor_to(s.emu, stage.map_index)
        navigation.enter_stage(s.emu)
        s.step(STAND_BEFORE_QUIT_FRAMES)
        navigation.pause_and_quit(s.emu)
        s.step(AFTER_LAST_QUIT_FRAMES)

    return play


def clear(stage):
    def play(s):
        plan = plans.load(stage.plan_path)
        s.note(f"replaying {stage.plan_path.name}: {plan.frames} frames")
        plans.replay(s.emu, plan)
        s.note("plan finished")
        navigation.wait_for_stage_clear(s.emu, stage.plan_path.name)
        for _ in range(STAGE_CLEAR_SHOTS):
            s.step(STAGE_CLEAR_SHOT_FRAMES)
            s.shot("stage-clear")
        s.rearm("after the clear: Stage Clear -> map, the next stage, a quit fire nothing")
        presses = navigation.leave_stage_clear(s.emu)
        s.note(f"left Stage Clear after {presses} CROSS press(es); entering the next stage")
        entered = navigation.enter_stage(s.emu)
        s.note(f"entered lid {entered:#x}; run, pause, SELECT")
        s.step(LEAVE_SPAWN_ZONE_FRAMES, [Btn.UP])
        s.step(STAND_BEFORE_QUIT_FRAMES)
        navigation.pause_and_quit(s.emu)
        s.step(AFTER_LAST_QUIT_FRAMES)

    return play


NOTHING_FIRES = {}
SCENARIOS = {
    "cold-boot": Scenario(None, NOTHING_FIRES, "3 minutes from power-on, no input", play_cold_boot),
    "attract": Scenario(None, NOTHING_FIRES, "15 minutes of attract-mode demos", play_attract),
}
SCENARIOS["game-over"] = Scenario(
    STAGES[0].start,
    NOTHING_FIRES,
    "deaths on N. Sanity Beach down to a game over",
    down_to_game_over(STAGES[0]),
)
for _stage in STAGES:
    SCENARIOS[f"{_stage.name}-deaths"] = Scenario(
        _stage.start, NOTHING_FIRES, f"three deaths on {_stage.name}", deaths(_stage)
    )
    SCENARIOS[f"{_stage.name}-quit"] = Scenario(
        _stage.start, NOTHING_FIRES, f"three pause -> SELECT quits of {_stage.name}", quits(_stage)
    )
    if _stage.plan_path.is_file():
        SCENARIOS[f"{_stage.name}-clear"] = Scenario(
            _stage.start,
            {_stage.level_id: LID_STAGE_CLEAR},
            f"{_stage.name} cleared by its plan, then the next stage quit (pcsx_rearmed only)",
            clear(_stage),
        )
    else:
        pass  # No clearing plan committed: the clear stays for the in-game check.


def on_expected_level(trigger, expected):
    """`expected` maps a title to its lid; an unexpected title is never on its level."""
    return expected.get(trigger.title) == trigger.level_id


def run(name, core):
    """Plays one scenario in this process; returns True when the triggers match expectations.

    Every expected achievement must fire exactly once, while the game shows its expected lid, and
    nothing else may fire: a trigger on another level fails even when its title was expected.
    """
    scenario = SCENARIOS[name]
    session = Session(name, state=scenario.start, core=core)
    session.note(scenario.about)
    scenario.play(session)
    triggers = session.close()
    expected = {achievements.level_title(stage): lid for stage, lid in scenario.expected.items()}
    off_level = [trigger for trigger in triggers if not on_expected_level(trigger, expected)]
    on_level = sorted(trigger.title for trigger in triggers if on_expected_level(trigger, expected))
    passed = not off_level and on_level == sorted(expected)
    verdict = "OK" if passed else "FAIL"
    wanted = [f"{title} on lid {lid:#x}" for title, lid in sorted(expected.items())]
    fired = [
        f"{trigger.title} at frame {trigger.frame} on lid {trigger.level_id:#x}"
        for trigger in triggers
    ]
    print(f"{verdict} {name}: expected {wanted}; triggered {fired}")
    return passed


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("names", nargs="+", choices=[*SCENARIOS, "all"], metavar="NAME")
    parser.add_argument("--core", default=DEFAULT_CORE, choices=sorted(CORE_DEFAULTS))
    args = parser.parse_args()
    names = list(SCENARIOS) if "all" in args.names else args.names
    if len(names) == 1:
        return 0 if run(names[0], args.core) else 1
    failed = []
    for name in names:
        child = subprocess.run([sys.executable, __file__, "--core", args.core, name], check=False)
        if child.returncode != 0:
            failed.append(name)
    print(f"{len(names) - len(failed)}/{len(names)} scenarios OK; failed: {failed or 'none'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
