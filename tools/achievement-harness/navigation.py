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
    TITLE_STATE_PASSWORD,
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
QUIT_STAND_FRAMES = 60  # SELECT does not quit while Crash is still moving or falling
STAGE_CLEAR_TIMEOUT_FRAMES = 600
CURSOR_MOVE_FRAMES = 90
# A cursor move onto another island's screen passes through the "going to next/prev world" camera;
# a CROSS pressed while Crash still walks the new screen's path is ignored.
ISLAND_CHANGE_SETTLE_FRAMES = 360
# Wumpa Island's screen (map stages Up the Creek to Koala Kong) runs right to left: RIGHT moves the
# cursor back along the path there.
REVERSED_MAP_CURSORS = range(0x09, 0x11)
# The secret stages hang off the path (measured): UP from Boulder Dash to Whole Hog, UP from Lights
# Out to Fumbling in the Dark; the main path never passes through them.
SECRET_STAGE_BRANCHES = {0x20: 0x0E, 0x1F: 0x18}
# The main path has 31 map stages, so a walk takes at most 30 moves; a press the map ignores (one
# landed while the camera still settled after an island change, measured) costs another, so twice.
MAP_PATH_MOVES = 60
ENTER_ATTEMPTS = 2
# The main menu ignores the pad while it slides in (measured: a DOWN 60 frames after it shows is
# lost, one 400 frames after is taken).
MAIN_MENU_INPUT_FRAMES = 400
PASSWORD_MENU_DOWN_PRESSES = 2  # START, LOAD GAME, PASSWORD
PASSWORD_SYMBOL_RELEASE_FRAMES = 20
PASSWORD_BUTTONS = {"T": Btn.TRIANGLE, "S": Btn.SQUARE, "O": Btn.CIRCLE, "X": Btn.CROSS}


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


def boot_to_password_map(emu, password):
    """Cold boot -> title menu -> PASSWORD -> `password` (T, S, O, X) -> island map."""
    wait_until(
        emu,
        lambda e: level_id(e) == LID_TITLE and e.s32(TITLE_STATE) == TITLE_STATE_MAIN_MENU,
        BOOT_TIMEOUT_FRAMES,
        "title menu",
    )
    emu.step(MAIN_MENU_INPUT_FRAMES)
    for _ in range(PASSWORD_MENU_DOWN_PRESSES):
        press(emu, Btn.DOWN)
    press_until(
        emu, Btn.CROSS, lambda e: e.s32(TITLE_STATE) == TITLE_STATE_PASSWORD, "password screen"
    )
    for symbol in password:
        press(emu, PASSWORD_BUTTONS[symbol], release=PASSWORD_SYMBOL_RELEASE_FRAMES)
    # CROSS leaves the screen: to the map after a valid password, to the main menu after
    # "INVALID PASSWORD". Pressing on from the main menu would start a new game instead.
    press_until(
        emu,
        Btn.CROSS,
        lambda e: e.s32(TITLE_STATE) != TITLE_STATE_PASSWORD,
        f"leaving the password screen after {password}",
    )
    if emu.s32(TITLE_STATE) != TITLE_STATE_WORLD_MAP:
        raise RuntimeError(
            f"password {password} rejected: title state {emu.s32(TITLE_STATE):#x}, not the map"
        )
    else:
        pass  # Accepted: the map loads.
    wait_until(emu, on_the_map, LOAD_TIMEOUT_FRAMES, "island map")
    emu.step(MAP_SETTLE_FRAMES)


def enter_stage(emu):
    """From the map, enters the stage under the cursor; returns its level id once playable.

    Presses CROSS again when the first press was ignored (Crash still walking the map's path).
    """
    for attempt in range(1, ENTER_ATTEMPTS + 1):
        press(emu, Btn.CROSS)
        try:
            wait_until(emu, playing_a_stage, LOAD_TIMEOUT_FRAMES, "player control in a stage")
            break
        except TimeoutError:
            if attempt == ENTER_ATTEMPTS or level_id(emu) != LID_TITLE or not on_the_map(emu):
                raise
            else:
                pass  # Still on the map: the press was ignored.
    emu.step(CONTROL_SETTLE_FRAMES)
    return level_id(emu)


def move_cursor_to(emu, map_index):
    """On the island map, walks the cursor along the path to stage `map_index` (`0x619C5`); a
    secret stage is reached with UP from the stage it branches off."""
    cursor = emu.u8(STAGE_ID)
    if cursor == map_index:
        return
    if cursor in SECRET_STAGE_BRANCHES:
        press(emu, Btn.DOWN, release=CURSOR_MOVE_FRAMES)
    else:
        pass  # On the main path already.
    branch = SECRET_STAGE_BRANCHES.get(map_index)
    if branch is None:
        _walk_path_to(emu, map_index)
        return
    _walk_path_to(emu, branch)
    press(emu, Btn.UP, release=CURSOR_MOVE_FRAMES)
    if emu.u8(STAGE_ID) != map_index:
        raise TimeoutError(f"UP from stage {branch} left the cursor on {emu.u8(STAGE_ID)}")
    else:
        pass  # On the secret stage.


def _walk_path_to(emu, map_index):
    """Walks the cursor along the main path to stage `map_index`."""
    for _ in range(MAP_PATH_MOVES):
        cursor = emu.u8(STAGE_ID)
        if cursor == map_index:
            return
        forward, back = Btn.RIGHT, Btn.LEFT
        if cursor in REVERSED_MAP_CURSORS:
            forward, back = back, forward
        else:
            pass  # Left to right, as N. Sanity Island and Cortex Island run.
        press(emu, forward if cursor < map_index else back, release=CURSOR_MOVE_FRAMES)
        if not on_the_map(emu):
            wait_until(emu, on_the_map, LOAD_TIMEOUT_FRAMES, "map after an island change")
            emu.step(ISLAND_CHANGE_SETTLE_FRAMES)
        else:
            pass  # Same island: the move settles within CURSOR_MOVE_FRAMES.
    if emu.u8(STAGE_ID) == map_index:
        return
    raise TimeoutError(
        f"map cursor on stage {emu.u8(STAGE_ID)}, not {map_index}, after {MAP_PATH_MOVES} moves"
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
