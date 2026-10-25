"""Crash Bandicoot (USA, SCUS-94900) RAM map and the named probes a trace records every frame.

Addresses are rcheevos addresses (PS1 `0x80xxxxxx` minus `0x80000000`). The `0x6188C`-`0x61A67`
block is the engine's GOOL globals array (global n at `0x6188C + 4n`), laid out and named by the
wurlyfox/c1 decompilation (`gool_globals`, `src/globals.h`). Most counters there are 24.8 fixed
point, which is why the RA code notes point at odd bytes (`0x618ED`, `0x61985`, `0x619C5`...).

Probe names: `rXXXXX` / `wXXXXX` are the raw 8-bit / 24-bit reads the repo's conditions make
(`0xHXXXXX` / `0xWXXXXX`); `g_*` are GOOL globals under their c1 names.
"""

import achievements
from harness import POINTER_BYTES

FIXED_POINT_SHIFT = 8
FIXED_POINT_BYTES = 4
DECIMAL_DIGIT_MAX = 9  # values up to 9 read the same in hex and decimal

# GOOL globals (c1 `gool_globals`).
LEVEL_ID = 0x6188D  # byte 1 of global 0, `lid << 8`: the loaded level file
NEXT_DISPLAY_FLAGS = 0x6189C  # leaves DISPLAY_FLAGS_NORMAL when the death camera starts
RESPAWN_COUNT = 0x618A0  # 24.8, +1 per in-level respawn, reset when the title LID loads
FRUIT_HUD_POINTER = 0x618A4
LIFE_HUD_POINTER = 0x618A8
PAUSE_OBJECT = 0x618BC
AKU_POINTER = 0x618CC  # null until the first level loads after power-on, never cleared after
GAME_STATE = 0x618D0
TITLE_STATE = 0x618D4
MAP_PROGRESS = 0x618DC
LIFE_COUNT = 0x618EC  # 24.8, committed copy of the player's lives
AKU_HEALTH = 0x618F0  # 24.8
FRUIT_COUNT = 0x618F4  # 24.8
TAWNA_TOKENS = 0x61900  # 24.8
LEVEL_COUNT = 0x61944
LEVELS_UNLOCKED = 0x61948  # map stages the island map spawns when it loads
PERCENT_COMPLETE = 0x61974
BONUS_ROUND_ID = 0x6197C
BOX_COUNT = 0x61984  # 24.8, boxes broken in the current stage
ITEM_POOL1 = 0x61988  # gem bits: bit n + 1 is the clear gem of map stage n (`0x619C5`)
GEM_STAMP = 0x61990
ISLAND_CAM_STATE = 0x61994  # RA "overworld status"
IS_FIRST_ZONE = 0x61998  # RA "on results screen"; really 1 after every load and every respawn
CHECKPOINT_ID = 0x619A0  # -1 until a checkpoint crate of the stage is broken
ITEM_POOL2 = 0x619AC  # gem and key bits
TITLE_PAUSE_STATE = 0x619B4
STAGE_ID = 0x619C5  # byte 1 of the map cursor global: RA "current stage"
GEM_COUNT = 0x61A10
KEY_COUNT = 0x61A14
PBAK_STATE = 0x61A30  # demo playback: 0 normal play, 3 demo picked, 2 demo playing
FADE_COUNTER = 0x61A34
DEATH_COUNT = 0x61A3C  # 24.8

# Engine variables outside the globals block.
PAUSED = 0x56400
PLAYER_POINTER = 0x566B4
BOSS_POINTER = 0x60DDC  # the boss object of a boss fight; reallocated on every respawn

AKU_LEVEL_OFFSET = 0x189
# The player object's counters, 24.8: Wumpa (wraps at 100 into an extra life), then lives (capped
# at 99). The Wumpa HUD only animates towards the player's count, a few frames behind.
PLAYER_FRUIT_OFFSET = 0x160
PLAYER_LIVES_OFFSET = 0x164
PLAYER_POSITION_OFFSETS = (0x80, 0x84, 0x88)
# c1 `state_flags`, copied from the object's current state. Bit 15, unnamed in c1, is set by the
# states that open a stage: N. Sanity Beach's wake-up, left on the first button, and the spin-in
# elsewhere, which ignores the pad.
PLAYER_STATE_FLAGS_OFFSET = 0x120
NO_CONTROL_STATE_FLAG = 0x8000
# The code notes give +0x06 as the first hop of the lives chain; only +0x6C reads the lives.
HUD_COUNT_CHAIN = (0x6C, 0xE4, 0x0C)
# A HUD object's own 24.8 copy of the count it shows, stepping with the digits.
HUD_COUNT_OFFSET = 0x160

# Level ids (c1 `LID_*`, src/common.h).
LID_TITLE = 0x19  # title screen, menus and the island map
LID_NSANITY_BEACH = 0x09
LID_PAPU_PAPU = 0x0A
LID_JUNGLE_ROLLERS = 0x0C
LID_BOULDERS = 0x0E
LID_UPSTREAM = 0x0F
LID_THE_GREAT_GATE = 0x12
LID_ROLLING_STONES = 0x15
LID_HOG_WILD = 0x11
LID_NATIVE_FORTRESS = 0x1A
LID_UP_THE_CREEK = 0x18
LID_RIPPER_ROO = 0x17
LID_THE_LOST_CITY = 0x20
LID_TEMPLE_RUINS = 0x1C
LID_ROAD_TO_NOWHERE = 0x14
LID_BOULDER_DASH = 0x13
LID_SUNSET_VISTA = 0x23
LID_KOALA_KONG = 0x21
LID_PINSTRIPE = 0x08
LID_HEAVY_MACHINERY = 0x06
LID_CORTEX_POWER = 0x03
LID_GENERATOR_ROOM = 0x05
LID_TOXIC_WASTE = 0x07
LID_THE_HIGH_ROAD = 0x16
LID_SLIPPERY_CLIMB = 0x2E
LID_LIGHTS_OUT = 0x28
LID_JAWS_OF_DARKNESS = 0x1D
LID_CASTLE_MACHINERY = 0x37
LID_NITRUS_BRIO = 0x1B
LID_THE_LAB = 0x29
LID_STAGE_CLEAR = 0x2D  # c1 `LID_LEVELEND`
NON_STAGE_LIDS = (LID_TITLE, LID_STAGE_CLEAR)
# A boss's 24.8 health word, by fight: a pointer, then the offsets to the word. Papu Papu and
# Pinstripe are the object BOSS_POINTER names; Ripper Roo is its first child's sibling (c1
# `children` +0x6C, `sibling` +0x68); Koala Kong hangs off KOALA_KONG_POINTER (code notes). Full
# health, measured: 3, 3, 4 and 6. The boss achievements do not read it (they fire on the fight's
# exit): the search scores the hits.
KOALA_KONG_POINTER = 0x61898
BOSS_HEALTH_CHAINS = {
    LID_PAPU_PAPU: (BOSS_POINTER, 0x104),
    LID_RIPPER_ROO: (BOSS_POINTER, 0x6C, 0x68, 0x104),
    LID_KOALA_KONG: (KOALA_KONG_POINTER, 0x6C, 0x104),
    LID_PINSTRIPE: (BOSS_POINTER, 0x104),
}
# Game states (c1 `GAME_STATE_*`, src/globals.h).
GAME_STATE_PLAYING = 0x100
GAME_STATE_GAME_OVER = 0x200
# c1 `GAME_STATE_CONTINUE`: leaving the Stage Clear screen, or a level won straight to the map
# without it (a boss beaten, a stage cleared after a death past a checkpoint).
GAME_STATE_LEVEL_WON = 0x300
GAME_STATE_QUIT = 0x400  # pause -> quit picked, until the title/map level loads
GAME_STATE_STAGE_CLEARED = 0x500  # c1 `GAME_STATE_NEW_GEM`: a stage cleared, Stage Clear next
TITLE_STATE_MAIN_MENU = 5
TITLE_STATE_PASSWORD = 0xE  # the ENTER PASSWORD screen
TITLE_STATE_WORLD_MAP = 0xF
ON_THE_MAP = 1
NO_CHECKPOINT = -1
PAUSED_ON = 1
DISPLAY_FLAGS_NORMAL = 0xFFFF


def u8(address):
    return lambda emu: emu.u8(address)


def u24(address):
    return lambda emu: emu.u24(address)


def u32(address):
    return lambda emu: emu.u32(address)


def s32(address):
    return lambda emu: emu.s32(address)


def fixed(address):
    """Integer part of a 24.8 fixed-point global."""
    return lambda emu: emu.s32(address) >> FIXED_POINT_SHIFT


def aku_level(emu):
    return emu.deref(AKU_POINTER, AKU_LEVEL_OFFSET)


def boss_health(emu):
    """The 24.8 health word of the loaded boss fight's boss (BOSS_HEALTH_CHAINS); None outside a
    known boss fight or on a null hop."""
    chain = BOSS_HEALTH_CHAINS.get(emu.u8(LEVEL_ID))
    if chain is None:
        return None
    pointer, *offsets = chain
    return emu.deref(pointer, *offsets, size=FIXED_POINT_BYTES)


def boss_object(emu):
    """The address of the object holding the boss's health (the last pointer of its chain); None
    outside a known boss fight or on a null hop."""
    chain = BOSS_HEALTH_CHAINS.get(emu.u8(LEVEL_ID))
    if chain is None:
        return None
    pointer, *offsets = chain
    if len(offsets) == 1:
        return emu.u24(pointer) or None
    return emu.deref(pointer, *offsets[:-1], size=POINTER_BYTES) or None


def has_gem(emu, map_index):
    """Whether the clear gem of map stage `map_index` (`0x619C5`) is won, at the bit the gem
    achievements read."""
    address, bit = achievements.advanced_seed().gem_bit_position(map_index)
    return bool(emu.u8(address) >> bit & 1)


def in_a_stage(emu):
    """The loaded level is a stage, not the title/map level nor the Stage Clear screen."""
    return emu.u8(LEVEL_ID) not in NON_STAGE_LIDS


def player_counter(offset):
    """A 24.8 counter of the player object; None outside a stage, where the player pointer names
    another object, and while the pointer is null."""

    def read(emu):
        if not in_a_stage(emu):
            return None
        value = emu.deref(PLAYER_POINTER, offset, size=FIXED_POINT_BYTES)
        if value is None:
            return None
        return value >> FIXED_POINT_SHIFT

    return read


box_count = fixed(BOX_COUNT)
player_lives = player_counter(PLAYER_LIVES_OFFSET)
player_fruit = player_counter(PLAYER_FRUIT_OFFSET)


def player_state_flags(emu):
    """The player object's state flags; None outside a stage and while the pointer is null."""
    if not in_a_stage(emu):
        return None
    return emu.deref(PLAYER_POINTER, PLAYER_STATE_FLAGS_OFFSET, size=FIXED_POINT_BYTES)


def hud_count(pointer):
    return lambda emu: emu.deref(pointer, *HUD_COUNT_CHAIN)


def hud_count_address(emu, pointer):
    """RA address of the count a HUD object shows (HUD_COUNT_CHAIN's last hop); None on a null
    hop."""
    address = emu.u24(pointer)
    for offset in HUD_COUNT_CHAIN[:-1]:
        if address == 0:
            return None
        address = emu.u24(address + offset)
    if address == 0:
        return None
    return address + HUD_COUNT_CHAIN[-1]


CONDITION_READS = [
    ("r6188d", u8(LEVEL_ID)),
]

# RA code-note addresses, traced next to the level id they are easily mistaken for.
CODE_NOTE_READS = [
    ("r61994", u8(ISLAND_CAM_STATE)),
    ("r61998", u8(IS_FIRST_ZONE)),
    ("r619c5", u8(STAGE_ID)),
    ("w618cc", u24(AKU_POINTER)),
]

GLOBALS = [
    ("g_game_state", u32(GAME_STATE)),
    ("g_title_state", s32(TITLE_STATE)),
    ("g_map_progress", s32(MAP_PROGRESS)),
    ("g_respawn_count", fixed(RESPAWN_COUNT)),
    ("g_death_count", fixed(DEATH_COUNT)),
    ("g_checkpoint_id", s32(CHECKPOINT_ID)),
    ("g_life_count", fixed(LIFE_COUNT)),
    ("g_health", fixed(AKU_HEALTH)),
    ("g_fruit_count", fixed(FRUIT_COUNT)),
    ("g_box_count", box_count),
    ("g_tawna_count", fixed(TAWNA_TOKENS)),
    ("g_bonus_round", s32(BONUS_ROUND_ID)),
    ("g_pause_obj", u32(PAUSE_OBJECT)),
    ("g_title_pause_state", s32(TITLE_PAUSE_STATE)),
    ("g_pbak_state", s32(PBAK_STATE)),
    ("g_fade_counter", s32(FADE_COUNTER)),
    ("g_level_count", s32(LEVEL_COUNT)),
    ("g_levels_unlocked", s32(LEVELS_UNLOCKED)),
    ("g_gem_stamp", u32(GEM_STAMP)),
    ("g_item_pool1", u32(ITEM_POOL1)),
    ("g_item_pool2", u32(ITEM_POOL2)),
    ("g_percent_complete", s32(PERCENT_COMPLETE)),
    ("g_gem_count", s32(GEM_COUNT)),
    ("g_key_count", s32(KEY_COUNT)),
]

OBJECTS = [
    ("paused", u8(PAUSED)),
    ("aku_level", aku_level),
    ("boss_health", boss_health),
    ("fruit_hud", hud_count(FRUIT_HUD_POINTER)),
    ("life_hud", hud_count(LIFE_HUD_POINTER)),
    ("player_ptr", u24(PLAYER_POINTER)),
    ("player_lives", player_lives),
    ("player_fruit", player_fruit),
    ("player_state_flags", player_state_flags),
]

ALL = CONDITION_READS + CODE_NOTE_READS + GLOBALS + OBJECTS

# Probes that change nearly every frame: kept in the CSV, left out of the change log.
NOISY = {"g_fade_counter", "player_ptr"}

SUMMARY_KEYS = [
    "r6188d",
    "r61994",
    "r61998",
    "r619c5",
    "w618cc",
    "g_game_state",
    "g_title_state",
    "g_respawn_count",
    "g_life_count",
    "g_fruit_count",
    "g_box_count",
    "player_fruit",
    "player_lives",
    "aku_level",
    "boss_health",
    "paused",
]


def format_value(value):
    """Hex above 9, decimal below, empty for a null pointer hop."""
    if value is None:
        return ""
    if isinstance(value, int):
        return f"{value:#x}" if value > DECIMAL_DIGIT_MAX else str(value)
    return str(value)


def summary(emu):
    readers = dict(ALL)
    return " ".join(f"{key}={format_value(readers[key](emu))}" for key in SUMMARY_KEYS)
