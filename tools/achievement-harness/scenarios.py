"""Recorded scenarios: scripted play from a derivable state, judged against the repo's achievements,
leaderboards and rich presence.

Each scenario states which achievements must trigger and the level (lid) the game must show when
they do (usually none: a death, a quit or the attract demo must never unlock anything), and exits
non-zero when a trigger is missing, repeated, unexpected or fires on another level. It states every
leaderboard attempt it plays and how each ends (submitted, canceled, reset by a state load or still
running), and fails on an attempt that starts anywhere but where the stage hands Crash to the
player, on a submitted or shown time that is not the frames played, on a submitted time that is not
the frames from the start to the win, and on a cancel without a quit or a game over. It also lists
the rich presence strings the game must show on the way (regular expressions), and fails when one
never shows or when a string names an unknown macro or level.

    python tools/achievement-harness/scenarios.py [--core CORE] NAME [NAME ...] | all

A core and the rcheevos runtime are process-global, so several scenarios run one per process.
"""

import argparse
import random
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field, replace

import achievements
import navigation
import plan as plans
import states
from explore import QUIT_MOVE
from harness import CORE_DEFAULTS, DEFAULT_CORE, FRAMES_PER_SECOND, SECONDS_PER_MINUTE, Btn
from probes import (
    BOX_COUNT,
    CHECKPOINT_ID,
    FIXED_POINT_SHIFT,
    FRUIT_HUD_POINTER,
    GAME_STATE,
    GAME_STATE_GAME_OVER,
    GAME_STATE_PLAYING,
    GAME_STATE_QUIT,
    HUD_COUNT_OFFSET,
    ITEM_POOL1,
    ITEM_POOL2,
    LID_STAGE_CLEAR,
    LID_TITLE,
    LIFE_HUD_POINTER,
    PAUSED,
    PAUSED_ON,
    PBAK_STATE,
    PLAYER_FRUIT_OFFSET,
    PLAYER_LIVES_OFFSET,
    PLAYER_POINTER,
    PLAYER_POSITION_OFFSETS,
    RESPAWN_COUNT,
    boss_health,
    box_count,
    has_gem,
    hud_count_address,
    in_a_stage,
)
from session import STATE_LOADED, Session
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
# A gem lands about 280 frames into the Stage Clear screen, before its "press X" prompt.
STAGE_CLEAR_SHOTS = 8
STAGE_CLEAR_SHOT_FRAMES = 60
DEATH_SEED = 1
PLAN_PREFIX_DIVISOR = 2  # deaths start halfway through a stage's clearing plan
LAST_HIT_HEALTH = 1 << FIXED_POINT_SHIFT  # a boss one hit from defeat: 1.0 in 24.8
# After a collectible event: the extra life of a Wumpa wrap lands about 110 frames later.
AFTER_EVENT_FRAMES = 300
# A held button moves Crash on the frame he gets control (after the spin-in) or 3 frames later
# (N. Sanity Beach's wake-up); more would mean the timer starts before he has control.
MAX_INPUT_LAG_FRAMES = 4
POSITION_BYTES = 4
_X_OFFSET, _Y_OFFSET, _Z_OFFSET = PLAYER_POSITION_OFFSETS
GROUND_AXES_OFFSETS = (_X_OFFSET, _Z_OFFSET)
MOVE_TIMEOUT_FRAMES = 2 * FRAMES_PER_SECOND
STAND_BEFORE_PAUSE_FRAMES = 60
# The community's 100% password, every stage, gem and key (crashbandicoot.fandom.com/wiki/Password,
# psxdatacenter.com/games/U/C/SCUS-94900.html). Measured: it sets all 26 gem bits and both keys
# while the title level is loaded.
ALL_GEMS_PASSWORD = "TTTTXSTTTTSXTOTTTOSTXXXX"
# Its `item_pool1` and `item_pool2`: the 26 gems and both keys, the mask of DuckStation's all-gems
# cheat for SCUS-94900.
ALL_GEMS_POOLS = (0x2FBDF7BE, 0x00140500)
AFTER_PASSWORD_FRAMES = 600
PAUSE_OPEN_FRAMES = 5 * FRAMES_PER_SECOND

HEADING_BUTTONS = {"up": Btn.UP, "down": Btn.DOWN, "right": Btn.RIGHT}
# Boxes of a stage, measured: those its clearing plan breaks plus those the Stage Clear screen then
# counts as missed (N. Sanity Beach 8 + 41, Jungle Rollers 12 + 26).
STAGE_BOXES = {"nsanity-beach": 49, "jungle-rollers": 38}

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

# How a leaderboard attempt ends.
SUBMITTED = "submitted"
CANCELED = "canceled"
RUNNING = "running"  # still timing when the scenario ends
RESET = "reset"  # cut short by a state load
LEADERBOARD_TITLES = {lb.level_id: lb.title for lb in achievements.leaderboard_definitions()}
LEADERBOARD_OPENINGS = {lb.level_id: lb.opening for lb in achievements.leaderboard_definitions()}
SUBMIT_LIDS = (LID_STAGE_CLEAR, LID_TITLE)
CANCEL_GAME_STATES = (GAME_STATE_QUIT, GAME_STATE_GAME_OVER)


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
    # leaderboard title -> how each of its attempts ends, in order (SUBMITTED, CANCELED, RESET,
    # RUNNING)
    leaderboards: dict = field(default_factory=dict)


def attempts_in(stage, *outcomes):
    """The leaderboard attempts a scenario plays in `stage`, by how each ends; none when the stage
    has no leaderboard."""
    title = LEADERBOARD_TITLES.get(stage.level_id)
    if title is None:
        return {}
    return {title: outcomes}


def opening_attempt(stage, outcome):
    """The attempt a scenario from `stage.start` plays: that state is saved 30 frames after the
    game state turns playing, which is inside a spin-in (the leaderboard starts when it ends) and
    after an intro has handed Crash over (nothing starts)."""
    if LEADERBOARD_OPENINGS.get(stage.level_id) == achievements.leaderboard_seed().SPIN_IN:
        return attempts_in(stage, outcome)
    return {}


def merged(*expectations):
    """Leaderboard expectations played one after the other: each title's attempts, in order."""
    attempts = defaultdict(tuple)
    for expectation in expectations:
        for title, outcomes in expectation.items():
            attempts[title] += tuple(outcomes)
    return dict(attempts)


def farming_attempts(stage, plan_path):
    """The attempts of goal_event on a plan whose farming quits and re-enters the stage
    (explore.QUIT_MOVE): each re-entry but the last ends canceled by the next quit, the last is cut
    short by the state load after the event, and the scenario's own re-entry ends canceled."""
    quits = plans.load(plan_path).macros.count(QUIT_MOVE)
    if quits == 0:
        return attempts_in(stage, CANCELED)
    return attempts_in(stage, *[CANCELED] * (quits - 1), RESET, CANCELED)


def next_stage(stage):
    """The stage the map cursor moves on to after `stage` is cleared."""
    for candidate in STAGES:
        if candidate.map_index == stage.map_index + 1:
            return candidate
    raise KeyError(f"no stage of STAGES follows {stage.name} on the map")


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


def play_password_all_gems(s):
    """Types the 100% password from the title menu: every gem and key bit set on the title level."""
    navigation.boot_to_password_map(s.emu, ALL_GEMS_PASSWORD)
    pools = (s.emu.u32(ITEM_POOL1), s.emu.u32(ITEM_POOL2))
    if pools != ALL_GEMS_POOLS:
        raise RuntimeError(f"password {ALL_GEMS_PASSWORD} loaded gem bits {pools}, not all 26")
    else:
        pass  # Every gem and key bit, set on the title level.
    s.note(f"password {ALL_GEMS_PASSWORD} loaded: gem bits {pools[0]:#010x} {pools[1]:#010x}")
    s.step(AFTER_PASSWORD_FRAMES)
    s.shot("map")


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
        if stage.can_idle:
            s.rearm("death 3: after idling where the player respawned")
            s.step(IDLE_IN_SPAWN_ZONE_FRAMES)
        else:
            s.rearm("death 3: no idling, the stage moves Crash on by itself")
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


def replay_until(s, inputs, predicate):
    """Replays `inputs` frame by frame until `predicate(emu)`; returns whether it held."""
    for frames, mask in inputs:
        for _ in range(frames):
            if predicate(s.emu):
                return True
            s.emu.run(1, mask)
    return predicate(s.emu)


def boss_deaths(stage, plan_path):
    """Deaths in a boss fight with the boss one hit from defeat, then right after the respawn.

    The winning plan is replayed up to the boss's last health; a respawn allocates a new boss at
    full health, so no death may pass for the final hit.
    """

    def play(s):
        rng = random.Random(DEATH_SEED)
        route = plans.load(plan_path).inputs
        if not replay_until(s, route, lambda emu: boss_health(emu) == LAST_HIT_HEALTH):
            raise RuntimeError(
                f"{plan_path.name} never left the boss at {LAST_HIT_HEALTH:#x} health"
            )
        s.note(f"boss at {LAST_HIT_HEALTH:#x} health after replaying {plan_path.name}; dying")
        die(s, stage, rng, "death 1", [])
        s.rearm("death 2: re-armed right after the respawn, the boss back at full health")
        die(s, stage, rng, "death 2", [])
        s.step(AFTER_DEATH_FRAMES)

    return play


def boss_death_after_last_hit(stage, plan_path):
    """The winning plan replayed until the boss's health is 0, then a death before the fight
    leaves: the respawn restarts the fight at full health, so the fight is not won.

    A TNT blast can take the boss's last health and Crash together (measured on Ripper Roo); a
    trigger on the health alone fires on that lost fight.
    """

    def play(s):
        rng = random.Random(DEATH_SEED)
        route = plans.load(plan_path).inputs
        if not replay_until(s, route, lambda emu: boss_health(emu) == 0):
            raise RuntimeError(f"{plan_path.name} never took the boss's last health")
        s.note(f"boss at 0 health after replaying {plan_path.name}; dying before the fight leaves")
        if not die(s, stage, rng, "death after the last hit", []):
            raise RuntimeError("game over instead of a respawn after the last hit")
        if navigation.level_id(s.emu) != stage.level_id:
            raise RuntimeError(f"the fight left for lid {navigation.level_id(s.emu):#x}")
        s.note(f"respawned in the fight, the boss back at {boss_health(s.emu):#x}")
        s.step(AFTER_DEATH_FRAMES)

    return play


def boss_win(stage, plan_path):
    """Replays the plan that wins the boss fight, up to the game state turning won; a state saved
    after the switch to the map is loaded back, and the boss fight is entered again and quit."""

    def play(s):
        plan = plans.load(plan_path)
        s.note(f"replaying {plan_path.name}: {plan.frames} frames, the fight won at its end")
        plans.replay(s.emu, plan)
        s.wait_until(
            lambda e: navigation.level_id(e) == LID_TITLE,
            navigation.LOAD_TIMEOUT_FRAMES,
            "the map level after the won fight",
        )
        s.step(AFTER_EVENT_FRAMES)
        s.note("save a state after the switch to the map and load it: every trigger to WAITING")
        s.emu.restore(s.emu.snapshot())
        s.wait_until(navigation.on_the_map, navigation.LOAD_TIMEOUT_FRAMES, "map after the boss")
        s.step(navigation.MAP_SETTLE_FRAMES)
        s.rearm("the boss fight entered again from the map and quit")
        navigation.move_cursor_to(s.emu, stage.map_index)
        entered = navigation.enter_stage(s.emu)
        s.note(f"entered lid {entered:#x}")
        s.step(QUIT_AFTER_CONTROL_FRAMES)
        navigation.pause_and_quit(s.emu)
        s.step(AFTER_LAST_QUIT_FRAMES)

    return play


def boss_quit(s):
    """Quits before the boss first reaches Crash: SELECT does nothing while he is being hit."""
    s.step(QUIT_AFTER_CONTROL_FRAMES)
    navigation.pause_and_quit(s.emu)
    s.step(AFTER_LAST_QUIT_FRAMES)


def poke_boxes(s, boxes):
    """SECONDARY EVIDENCE ONLY: sets the stage's box count, which the Stage Clear screen compares
    with the stage's boxes to hand out the gem. The gem bit itself is never written: the game
    sets it, or not."""
    s.emu.write_u32(BOX_COUNT, boxes << FIXED_POINT_SHIFT)
    s.note(f"POKED the box count to {boxes} (secondary evidence, not a played state)")


def split_inputs(inputs, frames):
    """`[frames, button_mask]` runs -> the runs of the first `frames` frames, and the rest."""
    head, tail, played = [], [], 0
    for run_frames, mask in inputs:
        if played + run_frames <= frames:
            head.append([run_frames, mask])
        elif played >= frames:
            tail.append([run_frames, mask])
        else:
            cut = frames - played
            head.append([cut, mask])
            tail.append([run_frames - cut, mask])
        played += run_frames
    return head, tail


def clear(stage, plan_path, boxes=None):
    """Replays a clearing plan; then Stage Clear -> map, the next stage and a quit fire nothing.

    `boxes`, when given, is poked as the box count before the plan's last segment (poke_boxes).
    """

    def play(s):
        plan = plans.load(plan_path)
        s.note(f"replaying {plan_path.name}: {plan.frames} frames")
        if boxes is None:
            plans.replay(s.emu, plan)
        else:
            head, tail = split_inputs(plan.inputs, plan.frames - plans.SEGMENT_FRAMES)
            plans.replay(s.emu, replace(plan, inputs=head))
            poke_boxes(s, boxes)
            plans.replay(s.emu, replace(plan, inputs=tail))
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


def checkpoint_death(stage, fruit=None, reload=True):
    """The checkpoint route, a death, then the clear searched from the checkpoint respawn.

    The game skips the Stage Clear screen after a death past a checkpoint: the clear ends straight
    on the map (game state `0x300`), so the stage's achievement fires there and the gem cannot.
    `fruit`, when given, is poked as the player's Wumpa after the respawn (poke_fruit). `reload`
    saves and loads a state at the respawn, as the clear was searched from; without it the run
    goes on live (the plan replays the same on the interpreter), so a leaderboard keeps timing.
    """

    def play(s):
        route = stage.goal_plan_path("checkpoint")
        s.note(f"replaying {route.name}: up to its checkpoint crate")
        plans.replay(s.emu, plans.load(route))
        s.note(f"checkpoint {s.emu.s32(CHECKPOINT_ID):#x}, {box_count(s.emu)} boxes; dying")
        states.die_by_random_play(s.emu, stage, states.CHECKPOINT_DEATH_SEED)
        s.note(f"respawned at the checkpoint with {box_count(s.emu)} boxes counted")
        if reload:
            s.emu.restore(s.emu.snapshot())  # as the respawn state the clear was searched from
            s.note("state reloaded (the frame count restarts at 0)")
        else:
            pass  # Live: the leaderboards keep their attempt.
        if fruit is not None:
            poke_fruit(s, fruit)
        else:
            pass  # The Wumpa the route collected.
        plan_path = stage.checkpoint_clear_plan_path
        plan = plans.load(plan_path)
        s.note(f"replaying {plan_path.name}: {plan.frames} frames")
        plans.replay(s.emu, plan)
        s.note(f"plan finished: game state {s.emu.u32(GAME_STATE):#x}")
        s.wait_until(navigation.on_the_map, navigation.LOAD_TIMEOUT_FRAMES, "map after the clear")
        s.note(f"on the map; gem bit {int(has_gem(s.emu, stage.map_index))}")
        s.step(AFTER_LAST_QUIT_FRAMES)

    return play


def poke_player_count(s, offset, hud_pointer, value, what):
    """SECONDARY EVIDENCE ONLY: sets a 24.8 count of the player object, and the HUD showing it so
    it shows the value without counting up and the run keeps the timing its plan was searched on.
    """
    player = s.emu.u24(PLAYER_POINTER)
    hud = s.emu.u24(hud_pointer)
    display = hud_count_address(s.emu, hud_pointer)
    if not player or not hud or display is None:
        raise RuntimeError(f"no player or {what} HUD to poke: not in a stage")
    fixed_value = value << FIXED_POINT_SHIFT
    s.emu.write_u32(player + offset, fixed_value)
    s.emu.write_u32(hud + HUD_COUNT_OFFSET, fixed_value)
    s.emu.write_u32(display, value)
    s.note(f"POKED the player's {what} to {value} (secondary evidence, not a played state)")


def poke_lives(s, lives):
    """Pokes the player's lives (poke_player_count): the cap is far out of a searched run's reach.
    The lives that then reach the cap are still real ones, earned by the replayed plan."""
    poke_player_count(s, PLAYER_LIVES_OFFSET, LIFE_HUD_POINTER, lives, "lives")


def poke_fruit(s, fruit):
    """Pokes the player's Wumpa (poke_player_count): the clear commits the count, so a run that
    picked up fruit, where the searched route picked up none."""
    poke_player_count(s, PLAYER_FRUIT_OFFSET, FRUIT_HUD_POINTER, fruit, "Wumpa")


def goal_event(stage, goal, start_lives=None):
    """Replays the stage's searched route to `goal` (explore.GOALS), whose last segment holds the
    event; then a state saved after it is loaded back, and the stage is quit, re-entered and quit.

    `start_lives`, when given, is poked in first (see poke_lives).
    """
    plan_path = stage.goal_plan_path(goal)

    def play(s):
        if start_lives is not None:
            poke_lives(s, start_lives)
        else:
            pass  # The lives the plan was searched with.
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


def entered_from_the_map(stage, then):
    """Enters `stage` from the map as its `-start` state does (so its plans replay), with the
    leaderboards active from the map; then plays `then`."""

    def play(s):
        navigation.move_cursor_to(s.emu, stage.map_index)
        entered = navigation.enter_stage(s.emu)
        s.note(f"entered lid {entered:#x} from the map")
        then(s)

    return play


def player_ground_position(emu):
    """The player object's x and z (not y: a fall or a landing changes it without any input), or
    None outside a stage or before the object exists."""
    if not in_a_stage(emu) or not emu.u24(PLAYER_POINTER):
        return None
    return tuple(
        emu.deref(PLAYER_POINTER, offset, size=POSITION_BYTES) for offset in GROUND_AXES_OFFSETS
    )


def started_attempts(s):
    return [event for event in s.leaderboard_events if event.kind == "started"]


def timed_pause_quit(stage):
    """Enters `stage` holding its heading from the frame its level loads, then opens the pause menu
    for a while and quits.

    Fails unless the leaderboard starts once and the player, still on the ground until then
    although the heading is held, first moves within MAX_INPUT_LAG_FRAMES of that frame. The
    judge then checks the run's time leaves out the frames the pause menu was open, and that the
    quit cancels it.
    """
    heading = [HEADING_BUTTONS[stage.heading]]

    def play(s):
        navigation.move_cursor_to(s.emu, stage.map_index)
        navigation.press(s.emu, Btn.CROSS)
        s.wait_until(
            lambda e: navigation.level_id(e) == stage.level_id,
            navigation.LOAD_TIMEOUT_FRAMES,
            f"{stage.name} level",
        )
        s.note(f"{stage.name} loaded; holding {stage.heading} until the player moves")
        before_start = []  # the player's ground position on every frame before the start
        for _ in range(navigation.LOAD_TIMEOUT_FRAMES):
            if started_attempts(s):
                break
            before_start.append(player_ground_position(s.emu))
            s.step(1, heading)
        else:
            raise TimeoutError(f"no leaderboard started in {stage.name}")
        start = started_attempts(s)[0]
        still = before_start[-1]
        s.wait_until(
            lambda e: player_ground_position(e) != still, MOVE_TIMEOUT_FRAMES, "a move", heading
        )
        lag = s.clock - start.clock
        held_still = {position for position in before_start if position is not None} == {still}
        s.note(
            f"the player first moved {lag} frames after the leaderboard started; still at "
            f"{still} on every frame before the start: {held_still}"
        )
        if not held_still or not 0 <= lag <= MAX_INPUT_LAG_FRAMES:
            raise RuntimeError(
                f"the player moved before the start or {lag} frames after it, "
                f"not within {MAX_INPUT_LAG_FRAMES}"
            )
        else:
            pass  # The run starts when the player gains control.
        s.step(STAND_BEFORE_PAUSE_FRAMES)
        navigation.press(s.emu, Btn.START)
        s.wait_until(lambda e: e.u8(PAUSED) == PAUSED_ON, navigation.LOAD_TIMEOUT_FRAMES, "pause")
        s.step(PAUSE_OPEN_FRAMES)
        navigation.press(s.emu, Btn.START)
        s.wait_until(lambda e: e.u8(PAUSED) != PAUSED_ON, navigation.LOAD_TIMEOUT_FRAMES, "resume")
        s.note(f"the pause menu was open; {s.played - start.played + 1} frames played so far")
        s.step(STAND_BEFORE_PAUSE_FRAMES)
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
SCENARIOS["password-all-gems"] = Scenario(
    None,
    NOTHING_FIRES,
    "the 100% password typed from the title menu, then the island map",
    play_password_all_gems,
    (TITLE_SCREEN, ISLAND_MAP),
)
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
    leaderboards=attempts_in(STAGES[0], RUNNING),
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
        leaderboards=opening_attempt(_stage, RUNNING),
    )
    SCENARIOS[f"{_stage.name}-quit"] = Scenario(
        _stage.start,
        NOTHING_FIRES,
        f"three pause -> SELECT quits of {_stage.name}",
        quits(_stage),
        (in_stage(_name), ISLAND_MAP),
        never=(NO_LIVES,),
        leaderboards=merged(
            opening_attempt(_stage, CANCELED), attempts_in(_stage, CANCELED, CANCELED)
        ),
    )
    if _stage.plan_path.is_file():
        SCENARIOS[f"{_stage.name}-clear"] = Scenario(
            _stage.start,
            {_name: LID_STAGE_CLEAR},
            f"{_stage.name} cleared by its plan, then the next stage quit (pcsx_rearmed only)",
            clear(_stage, _stage.plan_path),
            (in_stage(_name), STAGE_CLEAR, ISLAND_MAP),
            never=(NO_LIVES,),
            leaderboards=merged(
                opening_attempt(_stage, SUBMITTED), attempts_in(next_stage(_stage), CANCELED)
            ),
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
                leaderboards=farming_attempts(_stage, _stage.goal_plan_path(_goal)),
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
            leaderboards=farming_attempts(_stage, _stage.goal_plan_path("wumpa")),
        )
        SCENARIOS[f"{_stage.name}-lives-cap-poked"] = Scenario(
            _wumpa_start,
            _wumpa_lid,
            "SECONDARY EVIDENCE (RAM poke): lives set at the cap, then the Wumpa route's extra "
            "lives, which the cap swallows",
            goal_event(_stage, "wumpa", start_lives=_collectibles.MAX_LIVES),
            (in_stage(_name, str(_collectibles.MAX_LIVES)),),
            never=(NO_LIVES,),
            leaderboards=farming_attempts(_stage, _stage.goal_plan_path("wumpa")),
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
            leaderboards=merged(
                opening_attempt(_stage, SUBMITTED), attempts_in(next_stage(_stage), CANCELED)
            ),
        )
    else:
        pass  # Only the seeded stage has a no-Wumpa achievement to judge.
_advanced = achievements.advanced_seed()
_GEM_TITLES = {stage: title for title, stage, _map_index, _points in _advanced.GEM_ACHIEVEMENTS}
_GEM_STAGES = [stage for stage in STAGES if achievements.level_title(stage.level_id) in _GEM_TITLES]
for _stage in _GEM_STAGES:
    _name = achievements.level_title(_stage.level_id)
    _gem_title = _GEM_TITLES[_name]
    _gem_lids = {_name: LID_STAGE_CLEAR, _gem_title: LID_STAGE_CLEAR}
    _gem_plan = _stage.goal_plan_path("gem")
    if _gem_plan.is_file():
        SCENARIOS[f"{_stage.name}-gem"] = Scenario(
            _stage.start,
            _gem_lids,
            f"{_stage.name} cleared with every box by its plan, then the next stage quit",
            clear(_stage, _gem_plan),
            (in_stage(_name), STAGE_CLEAR, ISLAND_MAP),
            never=(NO_LIVES,),
            leaderboards=merged(
                opening_attempt(_stage, SUBMITTED), attempts_in(next_stage(_stage), CANCELED)
            ),
        )
    else:
        pass  # No searched gem run.
    if _stage.plan_path.is_file() and _stage.name in STAGE_BOXES:
        SCENARIOS[f"{_stage.name}-gem-poked"] = Scenario(
            _stage.start,
            _gem_lids,
            "SECONDARY EVIDENCE (RAM poke): the clearing plan with the box count set to every box "
            "of the stage before its last segment",
            clear(_stage, _stage.plan_path, boxes=STAGE_BOXES[_stage.name]),
            (in_stage(_name), STAGE_CLEAR, ISLAND_MAP),
            never=(NO_LIVES,),
            leaderboards=merged(
                opening_attempt(_stage, SUBMITTED), attempts_in(next_stage(_stage), CANCELED)
            ),
        )
        SCENARIOS[f"{_stage.name}-one-box-short-poked"] = Scenario(
            _stage.start,
            {_name: LID_STAGE_CLEAR},
            "SECONDARY EVIDENCE (RAM poke): the clearing plan with the box count set one short of "
            "every box of the stage before its last segment",
            clear(_stage, _stage.plan_path, boxes=STAGE_BOXES[_stage.name] - 1),
            (in_stage(_name), STAGE_CLEAR, ISLAND_MAP),
            never=(NO_LIVES,),
            leaderboards=merged(
                opening_attempt(_stage, SUBMITTED), attempts_in(next_stage(_stage), CANCELED)
            ),
        )
    else:
        pass  # No clearing plan or no measured box total to poke.
    if _stage.early_death_clear_plan_path.is_file() and _stage.name in STAGE_BOXES:
        SCENARIOS[f"{_stage.name}-early-death-gem-poked"] = Scenario(
            _stage.early_death_restart,
            _gem_lids,
            "SECONDARY EVIDENCE (RAM poke): a death before any checkpoint, then the clear from the "
            "restart with the box count set to every box of the stage before its last segment",
            clear(_stage, _stage.early_death_clear_plan_path, boxes=STAGE_BOXES[_stage.name]),
            (in_stage(_name), STAGE_CLEAR, ISLAND_MAP),
            never=(NO_LIVES,),
            leaderboards=attempts_in(next_stage(_stage), CANCELED),
        )
    else:
        pass  # No clear searched from a restart after an early death.
    if _stage.checkpoint_clear_plan_path.is_file():
        _straight_to_map = {_name: LID_TITLE}
        if _name == _collectibles.NO_WUMPA_STAGE:
            # The checkpoint route and the clear from the respawn pick up no Wumpa.
            _route_lids = {**_straight_to_map, _collectibles.NO_WUMPA_TITLE: _stage.level_id}
            SCENARIOS[f"{_stage.name}-checkpoint-death-fruit-poked"] = Scenario(
                _stage.start,
                _straight_to_map,
                "SECONDARY EVIDENCE (RAM poke): the checkpoint death and clear with one Wumpa "
                "poked after the respawn",
                checkpoint_death(_stage, fruit=1),
                (in_stage(_name), ISLAND_MAP),
                never=(NO_LIVES, STAGE_CLEAR),
            )
        else:
            _route_lids = _straight_to_map
        SCENARIOS[f"{_stage.name}-checkpoint-death"] = Scenario(
            _stage.start,
            _route_lids,
            "a death after the checkpoint, then the clear from the checkpoint straight to the map",
            checkpoint_death(_stage),
            (in_stage(_name), ISLAND_MAP),
            never=(NO_LIVES, STAGE_CLEAR),
        )
        if _stage.level_id in LEADERBOARD_TITLES:
            SCENARIOS[f"{_stage.name}-timed-checkpoint-death"] = Scenario(
                states.RECIPES[_stage.start].parent,
                _route_lids,
                f"{_stage.name} entered from the map, then as {_stage.name}-checkpoint-death "
                "without the state reload: the death stays in the timed run",
                entered_from_the_map(_stage, checkpoint_death(_stage, reload=False)),
                (in_stage(_name), ISLAND_MAP),
                never=(NO_LIVES, STAGE_CLEAR),
                leaderboards=attempts_in(_stage, SUBMITTED),
            )
        else:
            pass  # No leaderboard times this stage.
    else:
        pass  # No route from the checkpoint respawn to the clear.
_TIMED_STAGES = [stage for stage in STAGES if stage.level_id in LEADERBOARD_TITLES]
for _stage in _TIMED_STAGES:
    _name = achievements.level_title(_stage.level_id)
    _from_map = states.RECIPES[_stage.start].parent
    SCENARIOS[f"{_stage.name}-timed-pause-quit"] = Scenario(
        _from_map,
        NOTHING_FIRES,
        f"{_stage.name} entered holding its heading, the pause menu opened for a while, a quit",
        timed_pause_quit(_stage),
        (in_stage(_name), ISLAND_MAP),
        never=(NO_LIVES,),
        leaderboards=attempts_in(_stage, CANCELED),
    )
    if _stage.plan_path.is_file():
        SCENARIOS[f"{_stage.name}-timed-clear"] = Scenario(
            _from_map,
            {_name: LID_STAGE_CLEAR},
            f"{_stage.name} entered from the map and cleared by its plan, then the next stage quit",
            entered_from_the_map(_stage, clear(_stage, _stage.plan_path)),
            (in_stage(_name), STAGE_CLEAR, ISLAND_MAP),
            never=(NO_LIVES,),
            leaderboards={
                **attempts_in(_stage, SUBMITTED),
                **attempts_in(next_stage(_stage), CANCELED),
            },
        )
    else:
        pass  # No clearing plan: the timed clear stays for the in-game check.
SCENARIOS["nsanity-beach-timed-game-over"] = Scenario(
    states.RECIPES[STAGES[0].start].parent,
    NOTHING_FIRES,
    "N. Sanity Beach entered from the map, then deaths down to a game over",
    entered_from_the_map(STAGES[0], down_to_game_over(STAGES[0])),
    (in_stage(_beach, NEW_GAME_LIVES), in_stage(_beach, "0"), GAME_OVER),
    leaderboards=attempts_in(STAGES[0], CANCELED),
)
_BOSS_STAGES = {stage.level_id: stage for stage in BOSS_FIGHTS}
for _fight in _advanced.BOSS_FIGHTS:
    _boss = _BOSS_STAGES[_fight.level_id]
    SCENARIOS[f"{_boss.name}-quit"] = Scenario(
        _boss.start,
        NOTHING_FIRES,
        f"the {_fight.boss} boss fight, quit with pause -> SELECT right after gaining control",
        boss_quit,
        (fighting(_fight.boss, NEW_GAME_LIVES), ISLAND_MAP),
        never=(NO_LIVES,),
    )
    _boss_plan = _boss.goal_plan_path("boss")
    if _boss_plan.is_file():
        SCENARIOS[f"{_boss.name}-boss"] = Scenario(
            _boss.start,
            {_fight.title: LID_TITLE},
            f"{_boss.name} beaten by its searched plan, a state load, the map, a re-entry, a quit",
            boss_win(_boss, _boss_plan),
            (fighting(_fight.boss, NEW_GAME_LIVES), ISLAND_MAP),
            never=(NO_LIVES,),
        )
        SCENARIOS[f"{_boss.name}-deaths"] = Scenario(
            _boss.start,
            NOTHING_FIRES,
            f"two deaths in the {_boss.name} fight, the first with the boss one hit from defeat",
            boss_deaths(_boss, _boss_plan),
            (
                fighting(_fight.boss, NEW_GAME_LIVES),
                fighting(_fight.boss, LOW_LIVES),
            ),
            never=(NO_LIVES,),
        )
        if _boss.last_hit_can_kill:
            SCENARIOS[f"{_boss.name}-death-after-last-hit"] = Scenario(
                _boss.start,
                NOTHING_FIRES,
                f"the {_boss.name} plan up to the boss's last health lost, then a death",
                boss_death_after_last_hit(_boss, _boss_plan),
                (fighting(_fight.boss, NEW_GAME_LIVES), fighting(_fight.boss, LOW_LIVES)),
                never=(NO_LIVES,),
            )
        else:
            pass  # The boss's last hit cannot take Crash with it.
    else:
        pass  # No searched win: the boss achievement stays for the in-game check.


@dataclass
class Attempt:
    start: object  # the "started" LeaderboardEvent; None when an end came without one
    last: object  # the latest event with the value shown (started, updated or the submit)
    end: object = None  # the "canceled" or "submitted" LeaderboardEvent; None while running

    @property
    def outcome(self):
        if self.end is None:
            return RUNNING
        if self.end.kind == "submitted":
            return SUBMITTED
        if self.end.kind == STATE_LOADED:
            return RESET
        return CANCELED


def attempts(events):
    """One title's leaderboard events, in order -> its Attempts."""
    found = []
    for event in events:
        if event.kind == "started":
            found.append(Attempt(event, event))
        elif event.kind == STATE_LOADED:
            if found and found[-1].end is None:
                found[-1].end = event
            else:
                pass  # No attempt to cut short.
        elif found and found[-1].end is None:
            if event.kind == "updated":
                found[-1].last = event
            elif event.kind == "submitted":
                found[-1].last = event
                found[-1].end = event
            else:
                found[-1].end = event
        else:
            found.append(Attempt(None, event, event))  # An end, or a value, with no start.
    return found


def attempt_problems(title, attempt, level_id, opening, session):
    """What is wrong with one attempt: a start anywhere but where the player gains control of the
    stage, a time shown or submitted that is not the frames played since the start, a submitted
    time that is not the frames from the start to the win (no submitted run opens the pause
    menu), a cancel without a quit or a game over, or a submit off Stage Clear and the map."""
    if attempt.start is None:
        return [f"{title}: {attempt.last.kind} at clock {attempt.last.clock} with no start"]
    problems = []
    start = attempt.start
    if (start.clock, level_id, opening) not in session.handovers:
        problems.append(
            f"{title}: started at clock {start.clock} on lid {start.level_id:#x}, not where the "
            f"{opening} of lid {level_id:#x} handed Crash over ({session.handovers})"
        )
    else:
        pass  # Started when the player gained control.
    played_until = session.played if attempt.end is None else attempt.end.played
    played = played_until - start.played + 1  # the start frame is played
    if attempt.last.value != played:
        problems.append(
            f"{title}: {attempt.outcome} with {attempt.last.value} frames on the clock, "
            f"{played} played since the start"
        )
    else:
        pass  # The clock counted exactly the frames played.
    if attempt.outcome == CANCELED and attempt.end.game_state not in CANCEL_GAME_STATES:
        problems.append(
            f"{title}: canceled with the game state {attempt.end.game_state:#x}, "
            "neither a quit nor a game over"
        )
    elif attempt.outcome == SUBMITTED:
        problems += submit_problems(title, attempt, session)
    else:
        pass  # Running, cut short by a state load, or canceled by a quit or a game over.
    return problems


def submit_problems(title, attempt, session):
    """A submit off Stage Clear and the map, or with a time other than the frames from the start
    to the first win after it (session.wins, the frame the stage is won is not played)."""
    problems = []
    if attempt.end.level_id not in SUBMIT_LIDS:
        problems.append(f"{title}: submitted on lid {attempt.end.level_id:#x}")
    else:
        pass  # Submitted on Stage Clear or the map.
    start, end = attempt.start.clock, attempt.end.clock
    wins = [clock for clock in session.wins if start < clock <= end]
    if not wins:
        problems.append(f"{title}: submitted at clock {end} with no win since clock {start}")
    elif attempt.end.value != wins[0] - start:
        problems.append(
            f"{title}: submitted {attempt.end.value} frames, the stage was won "
            f"{wins[0] - start} frames after the start"
        )
    else:
        pass  # The time runs from the start to the win.
    return problems


def leaderboard_problems(scenario, session):
    """Every leaderboard's attempts must end as the scenario states, each judged by
    attempt_problems; returns the problems and a line per attempt for the verdict."""
    by_title = defaultdict(list)
    for event in session.leaderboard_events:
        by_title[event.title].append(event)
    stages = {lb.title: (lb.level_id, lb.opening) for lb in session.leaderboards}
    problems, lines = [], []
    for title in sorted(set(by_title) | set(scenario.leaderboards)):
        found = attempts(by_title[title])
        outcomes = tuple(attempt.outcome for attempt in found)
        wanted = tuple(scenario.leaderboards.get(title, ()))
        if outcomes != wanted:
            problems.append(f"{title}: attempts {outcomes}, expected {wanted}")
        else:
            pass  # As many attempts as expected, each ending as expected.
        for attempt in found:
            problems += attempt_problems(title, attempt, *stages[title], session)
            start_clock = attempt.start.clock if attempt.start else None
            lines.append(
                f"{title}: started at clock {start_clock}, {attempt.outcome} with "
                f"{attempt.last.value} frames on lid {attempt.last.level_id:#x}"
            )
    return problems, lines


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
    shown may match a `never` pattern. Every leaderboard attempt must end as the scenario states
    and pass attempt_problems.
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
    leaderboard_failures, leaderboard_lines = leaderboard_problems(scenario, session)
    passed = (
        not off_level
        and on_level == sorted(expected)
        and not missing
        and not broken
        and not leaderboard_failures
    )
    verdict = "OK" if passed else "FAIL"
    wanted = [f"{title} on lid {lid:#x}" for title, lid in sorted(expected.items())]
    fired = [
        f"{trigger.title} at frame {trigger.frame} on lid {trigger.level_id:#x}"
        for trigger in triggers
    ]
    for frame, text in session.presence:
        print(f"  presence frame {frame}: {text}")
    for line in leaderboard_lines:
        print(f"  leaderboard {line}")
    print(
        f"{verdict} {name}: expected {wanted}; triggered {fired}; "
        f"presence never shown {missing}; broken presence {broken}; "
        f"leaderboard problems {leaderboard_failures}"
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
