"""Recorded scenarios: scripted play from a derivable state, judged against the repo's achievements.

Each scenario states which level achievements must trigger and the level (lid) the game must show
when they do (usually none: a death, a quit or the attract demo must never unlock anything), and
exits non-zero when a trigger is missing, unexpected or fires on another level.

    python tools/achievement-harness/scenarios.py [--core CORE] NAME [NAME ...] | all

A core and the rcheevos runtime are process-global, so several scenarios run one per process.
"""

import argparse
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

import achievements
import navigation
import plan as plans
from harness import CORE_DEFAULTS, DEFAULT_CORE, Btn
from probes import (
    FIXED_POINT_SHIFT,
    GAME_STATE,
    GAME_STATE_PLAYING,
    LID_STAGE_CLEAR,
    RESPAWN_COUNT,
)
from session import Session
from states import NSANITY_BEACH_CLEAR_PLAN

FRAMES_PER_SECOND = 60
SECONDS_PER_MINUTE = 60
COLD_BOOT_FRAMES = 3 * SECONDS_PER_MINUTE * FRAMES_PER_SECOND
COLD_BOOT_SHOT_FRAMES = 10 * FRAMES_PER_SECOND
ATTRACT_FRAMES = 15 * SECONDS_PER_MINUTE * FRAMES_PER_SECOND
ATTRACT_SHOT_FRAMES = 30 * FRAMES_PER_SECOND
LEAVE_SPAWN_ZONE_FRAMES = 150
STAND_BEFORE_DEATH_FRAMES = 900
STAND_BEFORE_QUIT_FRAMES = 400
DEATH_TIMEOUT_FRAMES = 1800
AFTER_RESPAWN_FRAMES = 60
AFTER_REARM_FRAMES = 120
AFTER_DEATH_FRAMES = 300
IDLE_IN_SPAWN_ZONE_FRAMES = 600
QUIT_AFTER_CONTROL_FRAMES = 60
AFTER_LAST_QUIT_FRAMES = 600
STAGE_CLEAR_SHOTS = 5
STAGE_CLEAR_SHOT_FRAMES = 60

NSANITY_BEACH_STAGE = 0


@dataclass(frozen=True)
class Scenario:
    start: str | None  # a states.RECIPES name; None boots the disc
    expected: dict  # stage id -> the lid the game shows when its level achievement must trigger
    about: str
    play: Callable


def respawns(emu):
    return emu.s32(RESPAWN_COUNT) >> FIXED_POINT_SHIFT


def player_in_control(emu):
    return emu.u32(GAME_STATE) == GAME_STATE_PLAYING


def die_walking_up(s, label):
    """Holds UP until the next respawn (the first crab on N. Sanity Beach)."""
    before = respawns(s.emu)
    waited = s.wait_until(
        lambda e: respawns(e) != before, DEATH_TIMEOUT_FRAMES, label, buttons=[Btn.UP]
    )
    s.note(f"{label}: respawn count {before} -> {respawns(s.emu)} after {waited} frames of UP")
    s.wait_until(player_in_control, navigation.LOAD_TIMEOUT_FRAMES, f"control after {label}")


def play_cold_boot(s):
    for _ in range(COLD_BOOT_FRAMES // COLD_BOOT_SHOT_FRAMES):
        s.step(COLD_BOOT_SHOT_FRAMES)
        s.shot("periodic")


def play_attract(s):
    for _ in range(ATTRACT_FRAMES // ATTRACT_SHOT_FRAMES):
        s.step(ATTRACT_SHOT_FRAMES)
        s.shot("periodic")


def play_beach_deaths(s):
    s.note("walk out of the spawn zone, stand still, then walk into the crab")
    s.step(LEAVE_SPAWN_ZONE_FRAMES, [Btn.UP])
    s.step(STAND_BEFORE_DEATH_FRAMES)
    die_walking_up(s, "death 1")
    s.step(AFTER_RESPAWN_FRAMES)

    s.rearm("second death, right after a respawn")
    s.step(AFTER_REARM_FRAMES)
    die_walking_up(s, "death 2")
    s.step(AFTER_DEATH_FRAMES)

    s.rearm("third death, after idling in the spawn zone")
    s.step(IDLE_IN_SPAWN_ZONE_FRAMES)
    s.shot("idle-in-spawn-zone")
    die_walking_up(s, "death 3")
    s.step(AFTER_DEATH_FRAMES)


def play_beach_quit(s):
    s.note("A: walk out, stand long enough to arm the level achievement, pause, SELECT")
    s.step(LEAVE_SPAWN_ZONE_FRAMES, [Btn.UP])
    s.step(STAND_BEFORE_QUIT_FRAMES)
    navigation.pause_and_quit(s.emu)

    s.rearm("B: same quit after re-entering the stage")
    navigation.enter_stage(s.emu)
    s.step(LEAVE_SPAWN_ZONE_FRAMES, [Btn.UP])
    s.step(STAND_BEFORE_QUIT_FRAMES)
    navigation.pause_and_quit(s.emu)

    s.rearm("C: quit right after gaining control, never leaving the spawn zone")
    navigation.enter_stage(s.emu)
    s.step(QUIT_AFTER_CONTROL_FRAMES)
    navigation.pause_and_quit(s.emu)
    s.step(AFTER_LAST_QUIT_FRAMES)


def play_beach_clear(s):
    plan = plans.load(NSANITY_BEACH_CLEAR_PLAN)
    s.note(f"replaying {NSANITY_BEACH_CLEAR_PLAN.name}: {plan.frames} frames")
    plans.replay(s.emu, plan)
    s.note("plan finished")
    navigation.wait_for_stage_clear(s.emu, NSANITY_BEACH_CLEAR_PLAN.name)
    for _ in range(STAGE_CLEAR_SHOTS):
        s.step(STAGE_CLEAR_SHOT_FRAMES)
        s.shot("stage-clear")
    presses = navigation.leave_stage_clear(s.emu)
    s.note(f"left Stage Clear after {presses} CROSS press(es); entering the next stage")
    entered = navigation.enter_stage(s.emu)
    s.note(f"entered lid {entered:#x}; walk out, stand, pause, SELECT")
    s.step(LEAVE_SPAWN_ZONE_FRAMES, [Btn.UP])
    s.step(STAND_BEFORE_QUIT_FRAMES)
    navigation.pause_and_quit(s.emu)
    s.step(AFTER_LAST_QUIT_FRAMES)


NOTHING_FIRES = {}
SCENARIOS = {
    "cold-boot": Scenario(None, NOTHING_FIRES, "3 minutes from power-on, no input", play_cold_boot),
    "attract": Scenario(None, NOTHING_FIRES, "15 minutes of attract-mode demos", play_attract),
    "beach-deaths": Scenario(
        "nsanity-beach-start", NOTHING_FIRES, "three deaths on N. Sanity Beach", play_beach_deaths
    ),
    "beach-quit": Scenario(
        "nsanity-beach-start", NOTHING_FIRES, "three pause -> SELECT quits", play_beach_quit
    ),
    "beach-clear": Scenario(
        "nsanity-beach-start",
        {NSANITY_BEACH_STAGE: LID_STAGE_CLEAR},
        "N. Sanity Beach cleared by the plan, then Jungle Rollers quit (pcsx_rearmed only)",
        play_beach_clear,
    ),
}


def on_expected_level(trigger, expected):
    """`expected` maps a title to its lid; an unexpected title is never on its level."""
    return expected.get(trigger.title) == trigger.level_id


def run(name, core):
    """Plays one scenario in this process; returns True when the triggers match expectations.

    Every expected achievement must fire while the game shows its expected lid, and nothing else
    may fire: a trigger on another level fails even when its title was expected.
    """
    scenario = SCENARIOS[name]
    session = Session(name, state=scenario.start, core=core)
    session.note(scenario.about)
    scenario.play(session)
    triggers = session.close()
    expected = {achievements.level_title(stage): lid for stage, lid in scenario.expected.items()}
    off_level = [trigger for trigger in triggers if not on_expected_level(trigger, expected)]
    on_level = {trigger.title for trigger in triggers if on_expected_level(trigger, expected)}
    passed = not off_level and on_level == set(expected)
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
