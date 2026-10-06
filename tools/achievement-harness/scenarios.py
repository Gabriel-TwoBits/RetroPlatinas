"""Recorded scenarios: scripted play from a derivable state, judged against the repo's achievements
and rich presence.

Each scenario states which achievements must trigger and the level (lid) the game must show when
they do (usually none: a death, a quit or the attract demo must never unlock anything), and
exits non-zero when a trigger is missing, repeated, unexpected or fires on another level. It also
lists the rich presence strings the game must show on the way (regular expressions), and fails
when one never shows or when a string names an unknown macro or level.

    python tools/achievement-harness/scenarios.py [--core CORE] NAME [NAME ...] | all

A core and the rcheevos runtime are process-global, so several scenarios run one per process.
"""

import argparse
import random
import re
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
    HUD_COUNT_OFFSET,
    LID_STAGE_CLEAR,
    LID_TITLE,
    LIFE_HUD_POINTER,
    PBAK_STATE,
    PLAYER_LIVES_OFFSET,
    PLAYER_POINTER,
    RESPAWN_COUNT,
    hud_count_address,
)
from session import Session
from states import BOSS_FIGHTS, STAGES

COLD_BOOT_FRAMES = 3 * SECONDS_PER_MINUTE * FRAMES_PER_SECOND
COLD_BOOT_SHOT_FRAMES = 10 * FRAMES_PER_SECOND
ATTRACT_FRAMES = 15 * SECONDS_PER_MINUTE * FRAMES_PER_SECOND
ATTRACT_SHOT_FRAMES = 30 * FRAMES_PER_SECOND
FIRST_DEMO_TIMEOUT_FRAMES = COLD_BOOT_FRAMES
DEMO_TIMEOUT_FRAMES = 2 * SECONDS_PER_MINUTE * FRAMES_PER_SECOND
PLAY_AFTER_NEW_GAME_FRAMES = 400  # well past the rich presence counts' 60-frame settle
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
# After a collectible event: the extra life of a Wumpa wrap lands about 110 frames later.
AFTER_EVENT_FRAMES = 300

HEADING_BUTTONS = {"up": Btn.UP, "down": Btn.DOWN, "right": Btn.RIGHT}

# Rich presence strings (seed_crash1_rich_presence) as regular expressions. Stage names come from
# the level achievements' titles or are spelled out here, never from the script's own lookup.
STARTING_UP = "Starting up"
TITLE_SCREEN = "At the title screen"
INTRO = "Watching the intro"
ISLAND_MAP = "On the island map"
STAGE_CLEAR = "On the Stage Clear screen"
GAME_OVER = "Game Over"
ANY_COUNT = r"\d+"
LOW_LIVES = "[0-3]"  # a new game's 4 lives after a death, extra lives picked up on the way aside
NEW_GAME_LIVES = "4"
# 0 lives where the last life is never reached: the read of a freed player object's null pointer.
NO_LIVES = r".* · 0 lives( · .*)?"
ATTRACT_DEMOS = (
    "Jungle Rollers",
    "The Great Gate",
    "Boulders",
    "Papu Papu",
    "The Lost City",
    "Jaws of Darkness",
    "The Lab",
)
BROKEN_PRESENCE = ("[Unknown macro]", "an unknown level")


def demo_of(name):
    return f"Watching a demo of {re.escape(name)}"


def in_stage(name, lives=ANY_COUNT):
    return rf"In {re.escape(name)} · {lives} li(fe|ves) · {ANY_COUNT} Wumpa"


def fighting(name, lives=ANY_COUNT):
    return rf"Fighting {re.escape(name)} · {lives} li(fe|ves)"


@dataclass(frozen=True)
class Scenario:
    start: str | None  # a states.RECIPES name; None boots the disc
    expected: dict  # achievement title -> the lid the game shows when it must trigger
    about: str
    play: Callable
    presence: tuple  # patterns each matched in full by at least one rich presence string shown
    never: tuple = ()  # patterns no rich presence string shown may match in full


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


def demo_playing(emu):
    return emu.s32(PBAK_STATE) != 0 and navigation.level_id(emu) != LID_TITLE


def play_attract_then_new_game(s):
    """Sits through the first attract demo, then starts a new game and enters N. Sanity Beach."""
    s.wait_until(demo_playing, FIRST_DEMO_TIMEOUT_FRAMES, "first attract demo")
    s.wait_until(
        lambda e: navigation.level_id(e) == LID_TITLE, DEMO_TIMEOUT_FRAMES, "title after the demo"
    )
    s.note("demo over; NEW GAME")
    navigation.boot_to_map(s.emu)
    entered = navigation.enter_stage(s.emu)
    s.note(f"entered lid {entered:#x}")
    s.step(PLAY_AFTER_NEW_GAME_FRAMES)


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


def boss_quit(s):
    """Quits before the boss first reaches Crash: SELECT does nothing while he is being hit."""
    s.step(QUIT_AFTER_CONTROL_FRAMES)
    navigation.pause_and_quit(s.emu)
    s.step(AFTER_LAST_QUIT_FRAMES)


def clear(stage, plan_path):
    def play(s):
        plan = plans.load(plan_path)
        s.note(f"replaying {plan_path.name}: {plan.frames} frames")
        plans.replay(s.emu, plan)
        s.note("plan finished")
        navigation.wait_for_stage_clear(s.emu, plan_path.name)
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


def poke_lives(s, lives):
    """SECONDARY EVIDENCE ONLY: sets the player's lives (and the lives HUD, so it shows them
    without counting up and the run keeps the timing its plan was searched on).

    The harness's only write to a counter an achievement reads (`map-unlocked`'s
    `levels_unlocked` write only reaches a stage): the cap is far out of a searched run's reach.
    The lives that then reach the cap are still real ones, earned by the replayed plan.
    """
    player = s.emu.u24(PLAYER_POINTER)
    hud = s.emu.u24(LIFE_HUD_POINTER)
    display = hud_count_address(s.emu, LIFE_HUD_POINTER)
    if not player or not hud or display is None:
        raise RuntimeError("no player or lives HUD to poke: not in a stage")
    fixed_lives = lives << FIXED_POINT_SHIFT
    s.emu.write_u32(player + PLAYER_LIVES_OFFSET, fixed_lives)
    s.emu.write_u32(hud + HUD_COUNT_OFFSET, fixed_lives)
    s.emu.write_u32(display, lives)
    s.note(f"POKED the player's lives to {lives} (secondary evidence, not a played state)")


def goal_event(stage, goal, start_lives=None):
    """Replays the stage's searched route to `goal` (explore.GOALS), whose last segment holds the
    event; then a state saved after it is loaded back, and the stage is quit, re-entered and quit.

    `start_lives`, when given, is poked in first (see poke_lives).
    """
    plan_path = stage.goal_plan_path(goal)

    def play(s):
        if start_lives is not None:
            poke_lives(s, start_lives)
        plan = plans.load(plan_path)
        s.note(f"replaying {plan_path.name}: {plan.frames} frames, the event in the last segment")
        plans.replay(s.emu, plan)
        s.step(AFTER_EVENT_FRAMES)
        s.note("save a state after the event and load it: every trigger back to WAITING")
        after_event = s.emu.snapshot()
        s.emu.restore(after_event)
        s.note("state loaded (the frame count restarts at 0)")
        s.step(AFTER_EVENT_FRAMES)
        s.rearm("quit, re-enter the stage with the counts the quit committed, stand, quit")
        navigation.pause_and_quit(s.emu)
        entered = navigation.enter_stage(s.emu)
        s.note(f"entered lid {entered:#x}")
        s.step(STAND_BEFORE_QUIT_FRAMES)
        navigation.pause_and_quit(s.emu)
        s.step(AFTER_LAST_QUIT_FRAMES)

    return play


NOTHING_FIRES = {}
SCENARIOS = {
    "cold-boot": Scenario(
        None,
        NOTHING_FIRES,
        "3 minutes from power-on, no input",
        play_cold_boot,
        (STARTING_UP, TITLE_SCREEN, INTRO, demo_of(ATTRACT_DEMOS[0])),
    ),
    "attract": Scenario(
        None,
        NOTHING_FIRES,
        "15 minutes of attract-mode demos",
        play_attract,
        (TITLE_SCREEN, INTRO, *(demo_of(name) for name in ATTRACT_DEMOS)),
    ),
}
_beach = achievements.level_title(STAGES[0].level_id)
SCENARIOS["game-over"] = Scenario(
    STAGES[0].start,
    NOTHING_FIRES,
    "deaths on N. Sanity Beach down to a game over",
    down_to_game_over(STAGES[0]),
    (in_stage(_beach, NEW_GAME_LIVES), in_stage(_beach, "0"), GAME_OVER),
)
SCENARIOS["attract-then-new-game"] = Scenario(
    None,
    NOTHING_FIRES,
    "the first attract demo, then a new game into N. Sanity Beach",
    play_attract_then_new_game,
    (demo_of(ATTRACT_DEMOS[0]), TITLE_SCREEN, ISLAND_MAP, in_stage(_beach, NEW_GAME_LIVES)),
    never=(demo_of(_beach), NO_LIVES),
)
for _stage in STAGES:
    _name = achievements.level_title(_stage.level_id)
    SCENARIOS[f"{_stage.name}-deaths"] = Scenario(
        _stage.start,
        NOTHING_FIRES,
        f"three deaths on {_stage.name}",
        deaths(_stage),
        (in_stage(_name, NEW_GAME_LIVES), in_stage(_name, LOW_LIVES)),
        never=(NO_LIVES,),
    )
    SCENARIOS[f"{_stage.name}-quit"] = Scenario(
        _stage.start,
        NOTHING_FIRES,
        f"three pause -> SELECT quits of {_stage.name}",
        quits(_stage),
        (in_stage(_name), ISLAND_MAP),
        never=(NO_LIVES,),
    )
    if _stage.plan_path.is_file():
        SCENARIOS[f"{_stage.name}-clear"] = Scenario(
            _stage.start,
            {_name: LID_STAGE_CLEAR},
            f"{_stage.name} cleared by its plan, then the next stage quit (pcsx_rearmed only)",
            clear(_stage, _stage.plan_path),
            (in_stage(_name), STAGE_CLEAR, ISLAND_MAP),
            never=(NO_LIVES,),
        )
    else:
        pass  # No clearing plan committed: the clear stays for the in-game check.
_collectibles = achievements.collectible_seed()
_GOAL_TITLES = (("wumpa", _collectibles.WUMPA_TITLE), ("aku", _collectibles.AKU_TITLE))
for _stage in STAGES:
    _name = achievements.level_title(_stage.level_id)
    for _goal, _title in _GOAL_TITLES:
        if _stage.goal_plan_path(_goal).is_file():
            SCENARIOS[f"{_stage.name}-{_goal}"] = Scenario(
                plans.load(_stage.goal_plan_path(_goal)).start,
                {_title: _stage.level_id},
                f"{_stage.name}: the searched route to {_title!r}, a state load after it, a quit",
                goal_event(_stage, _goal),
                (in_stage(_name), ISLAND_MAP),
                never=(NO_LIVES,),
            )
        else:
            pass  # No searched route to this event in this stage.
    if _stage.goal_plan_path("wumpa").is_file():
        _wumpa_lid = {_collectibles.WUMPA_TITLE: _stage.level_id}
        _wumpa_start = plans.load(_stage.goal_plan_path("wumpa")).start
        SCENARIOS[f"{_stage.name}-lives-poked"] = Scenario(
            _wumpa_start,
            {**_wumpa_lid, _collectibles.LIVES_TITLE: _stage.level_id},
            "SECONDARY EVIDENCE (RAM poke): lives set one below the cap, then the Wumpa route's "
            "real extra lives",
            goal_event(_stage, "wumpa", start_lives=_collectibles.MAX_LIVES - 1),
            (in_stage(_name, str(_collectibles.MAX_LIVES)),),
            never=(NO_LIVES,),
        )
        SCENARIOS[f"{_stage.name}-lives-cap-poked"] = Scenario(
            _wumpa_start,
            _wumpa_lid,
            "SECONDARY EVIDENCE (RAM poke): lives set at the cap, then the Wumpa route's extra "
            "lives, which the cap swallows",
            goal_event(_stage, "wumpa", start_lives=_collectibles.MAX_LIVES),
            (in_stage(_name, str(_collectibles.MAX_LIVES)),),
            never=(NO_LIVES,),
        )
    else:
        pass  # The poked lives scenarios ride on the Wumpa route.
    _no_wumpa_plan = _stage.goal_plan_path("no-wumpa")
    if _name == _collectibles.NO_WUMPA_STAGE and _no_wumpa_plan.is_file():
        SCENARIOS[f"{_stage.name}-no-wumpa"] = Scenario(
            _stage.start,
            {_name: LID_STAGE_CLEAR, _collectibles.NO_WUMPA_TITLE: _stage.level_id},
            f"{_stage.name} cleared without a Wumpa by its plan, then the next stage quit",
            clear(_stage, _no_wumpa_plan),
            (in_stage(_name), STAGE_CLEAR, ISLAND_MAP),
            never=(NO_LIVES,),
        )
    else:
        pass  # Only the seeded stage has a no-Wumpa achievement to judge.
SCENARIOS["papu-papu-quit"] = Scenario(
    BOSS_FIGHTS[0].start,
    NOTHING_FIRES,
    "the Papu Papu boss fight, quit with pause -> SELECT right after gaining control",
    boss_quit,
    (fighting("Papu Papu", NEW_GAME_LIVES), ISLAND_MAP),
    never=(NO_LIVES,),
)


def on_expected_level(trigger, expected):
    """`expected` maps a title to its lid; an unexpected title is never on its level."""
    return expected.get(trigger.title) == trigger.level_id


def presence_problems(scenario, shown):
    """Patterns no shown string matched, and shown strings naming an unknown macro or level or
    matching a `never` pattern."""
    texts = [text for _frame, text in shown]
    missing = [
        pattern
        for pattern in scenario.presence
        if not any(re.fullmatch(pattern, text) for text in texts)
    ]
    broken = sorted(
        {
            text
            for text in texts
            if any(mark in text for mark in BROKEN_PRESENCE)
            or any(re.fullmatch(pattern, text) for pattern in scenario.never)
        }
    )
    return missing, broken


def run(name, core):
    """Plays one scenario in this process; returns True when triggers and presence match.

    Every expected achievement must fire exactly once, while the game shows its expected lid, and
    nothing else may fire: a trigger on another level fails even when its title was expected.
    Every expected rich presence pattern must match a string shown on the way, and no string
    shown may match a `never` pattern.
    """
    scenario = SCENARIOS[name]
    session = Session(name, state=scenario.start, core=core)
    session.note(scenario.about)
    scenario.play(session)
    triggers = session.close()
    expected = scenario.expected
    off_level = [trigger for trigger in triggers if not on_expected_level(trigger, expected)]
    on_level = sorted(trigger.title for trigger in triggers if on_expected_level(trigger, expected))
    missing, broken = presence_problems(scenario, session.presence)
    passed = not off_level and on_level == sorted(expected) and not missing and not broken
    verdict = "OK" if passed else "FAIL"
    wanted = [f"{title} on lid {lid:#x}" for title, lid in sorted(expected.items())]
    fired = [
        f"{trigger.title} at frame {trigger.frame} on lid {trigger.level_id:#x}"
        for trigger in triggers
    ]
    for frame, text in session.presence:
        print(f"  presence frame {frame}: {text}")
    print(
        f"{verdict} {name}: expected {wanted}; triggered {fired}; "
        f"presence never shown {missing}; broken presence {broken}"
    )
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
