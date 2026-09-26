"""Scripted menu and map navigation, driven by RAM state rather than fixed delays.

Frame counts are part of the recipes in states.py: changing one re-derives every state, and input
plans searched from the old states may stop replaying. `states.py nsanity-beach-clear` checks the
clearing plan still replays after any change.
"""

from harness import Btn
from probes import (
    GAME_STATE,
    GAME_STATE_PLAYING,
    ISLAND_CAM_STATE,
    LEVEL_ID,
    LID_STAGE_CLEAR,
    LID_TITLE,
    ON_THE_MAP,
    PAUSED,
    PAUSED_ON,
    STAGE_ID,
    TITLE_STATE,
    TITLE_STATE_MAIN_MENU,
    TITLE_STATE_WORLD_MAP,
    in_a_stage,
)

PRESS_FRAMES = 4
RELEASE_FRAMES = 12
BOOT_TIMEOUT_FRAMES = 6000
LOAD_TIMEOUT_FRAMES = 3000
TITLE_MENU_SETTLE_FRAMES = 60
MENU_RETRY_FRAMES = 60
MENU_ATTEMPTS = 20
MAP_SETTLE_FRAMES = 120
CONTROL_SETTLE_FRAMES = 30
PAUSE_SETTLE_FRAMES = 60
STAGE_CLEAR_TIMEOUT_FRAMES = 600
CURSOR_MOVE_FRAMES = 90


def wait_until(emu, predicate, max_frames, what, buttons=()):
    """Steps one frame at a time until `predicate(emu)`; returns the frames waited."""
    for waited in range(max_frames):
        if predicate(emu):
            return waited
        emu.step(1, buttons)
    raise TimeoutError(f"{what} not reached within {max_frames} frames (frame {emu.frame})")


def press(emu, button, release=RELEASE_FRAMES):
    emu.step(PRESS_FRAMES, [button])
    emu.step(release)


def press_until(emu, button, predicate, what):
    """Presses `button` every MENU_RETRY_FRAMES until `predicate(emu)`; returns the press count."""
    for attempt in range(1, MENU_ATTEMPTS + 1):
        press(emu, button, release=MENU_RETRY_FRAMES)
        if predicate(emu):
            return attempt
    raise TimeoutError(f"{what} not reached after {MENU_ATTEMPTS} presses (frame {emu.frame})")


def level_id(emu):
    return emu.u8(LEVEL_ID)


def on_the_map(emu):
    return emu.u8(ISLAND_CAM_STATE) == ON_THE_MAP


def playing_a_stage(emu):
    return in_a_stage(emu) and emu.u32(GAME_STATE) == GAME_STATE_PLAYING


def boot_to_map(emu):
    """Cold boot -> title menu -> START (NEW GAME) -> island map, cursor on N. Sanity Beach."""
    wait_until(
        emu,
        lambda e: level_id(e) == LID_TITLE and e.s32(TITLE_STATE) == TITLE_STATE_MAIN_MENU,
        BOOT_TIMEOUT_FRAMES,
        "title menu",
    )
    emu.step(TITLE_MENU_SETTLE_FRAMES)
    press_until(emu, Btn.START, lambda e: e.s32(TITLE_STATE) == TITLE_STATE_WORLD_MAP, "NEW GAME")
    wait_until(emu, on_the_map, LOAD_TIMEOUT_FRAMES, "island map")
    emu.step(MAP_SETTLE_FRAMES)


def enter_stage(emu):
    """From the map, enters the stage under the cursor; returns its level id once playable."""
    press(emu, Btn.CROSS)
    wait_until(emu, playing_a_stage, LOAD_TIMEOUT_FRAMES, "player control in a stage")
    emu.step(CONTROL_SETTLE_FRAMES)
    return level_id(emu)


def move_cursor_to(emu, map_index):
    """On the island map, walks the cursor along the path to stage `map_index` (`0x619C5`)."""
    for _ in range(MENU_ATTEMPTS):
        cursor = emu.u8(STAGE_ID)
        if cursor == map_index:
            return
        if cursor < map_index:
            press(emu, Btn.RIGHT, release=CURSOR_MOVE_FRAMES)
        else:
            press(emu, Btn.LEFT, release=CURSOR_MOVE_FRAMES)
    raise TimeoutError(
        f"map cursor on stage {emu.u8(STAGE_ID)}, not {map_index}, after {MENU_ATTEMPTS} moves"
    )


def pause_and_quit(emu):
    """Pauses the stage and quits to the map with SELECT."""
    press(emu, Btn.START)
    wait_until(emu, lambda e: e.u8(PAUSED) == PAUSED_ON, LOAD_TIMEOUT_FRAMES, "pause menu")
    emu.step(PAUSE_SETTLE_FRAMES)
    press(emu, Btn.SELECT)
    wait_until(emu, on_the_map, LOAD_TIMEOUT_FRAMES, "map after quitting")
    emu.step(MAP_SETTLE_FRAMES)


def leave_stage_clear(emu):
    """From the Stage Clear screen, continues to the map; returns the CROSS presses it took."""
    presses = press_until(
        emu, Btn.CROSS, lambda e: level_id(e) != LID_STAGE_CLEAR, "leaving Stage Clear"
    )
    wait_until(emu, on_the_map, LOAD_TIMEOUT_FRAMES, "map after Stage Clear")
    emu.step(MAP_SETTLE_FRAMES)
    return presses


def wait_for_stage_clear(emu, plan_name):
    """Waits for the Stage Clear screen at the end of a plan that should clear the stage."""
    wait_until(
        emu,
        lambda e: level_id(e) == LID_STAGE_CLEAR,
        STAGE_CLEAR_TIMEOUT_FRAMES,
        f"Stage Clear after {plan_name} (a diverged plan needs a new search: explore.py)",
    )
