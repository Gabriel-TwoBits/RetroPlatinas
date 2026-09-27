from django.core.management.base import BaseCommand
from django.db import transaction

from apps.achievements.management.commands.seed_crash1_level_achievements import (
    LEVEL_ID_ADDRESS,
    STAGE_CLEAR_LEVEL_ID,
    rcheevos_hex,
)
from apps.achievements.management.crash1 import seed_crash1_game

# c1 level ids (`LID_*`, src/common.h) that are not stages; 0 is RAM before the first level loads.
POWER_ON_LEVEL_ID = 0x00
TITLE_LEVEL_ID = 0x19  # title screens, menus, game over screen and island map
INTRO_LEVEL_ID = 0x38
ENDING_LEVEL_ID = 0x39

# c1 `game_state >> 8`: 2 from the fatal hit of the last life until the title level loads; 6
# (`GAME_STATE_TITLE`) only in the attract loop, from the end of a demo or the intro.
GAME_STATE_ADDRESS = "0xH618d1"
GAME_STATE_GAME_OVER = 2
GAME_STATE_ATTRACT = 6
# c1 `title_state`: the screen the title level shows (title.c `TitleLoadState`).
TITLE_STATE_ADDRESS = "0xH618d4"
TITLE_STATE_MAP = 0x0F
TITLE_SCREEN = "At the title screen"
TITLE_SCREENS = {
    0x05: TITLE_SCREEN,  # main menu
    0x06: TITLE_SCREEN,  # options
    0x0C: "Game Over",
    0x0D: TITLE_SCREEN,  # password
    0x0E: TITLE_SCREEN,  # load game
}
STARTING_UP = "Starting up"  # power-on and the Sony, Universal and Naughty Dog screens
# c1 `pbak_state`: non-zero from the moment an attract demo is picked until about 18 frames
# before its level switches back to the title, where GAME_STATE_ATTRACT has already taken over.
DEMO_PLAYBACK_ADDRESS = "0xH61a30"
# The player object's lives (24.8 at +0x164, the integer's low byte at +0x165).
LIVES_VALUE = "I:0xW566b4_M:0xH165"
# The Wumpa HUD object: pointer, +0x6c, +0xe4, and the count at +0x0c.
WUMPA_VALUE = "I:0xW618a4_I:0xW6c_I:0xWe4_M:0xHc"
# Both objects hold leftovers of the previous level for up to about 20 frames after a level loads
# (120 lives, 144 Wumpa...), so the counts show only once the level id has held this long.
LEVEL_SETTLE_FRAMES = 60
LEVEL_SETTLED = (
    f"R:{LEVEL_ID_ADDRESS}!=d{LEVEL_ID_ADDRESS}_"
    f"{LEVEL_ID_ADDRESS}={LEVEL_ID_ADDRESS}.{LEVEL_SETTLE_FRAMES}."
)

# c1 level id -> name, for the stages, the boss fights and the bonus rounds.
STAGES = {
    0x03: "Cortex Power",
    0x05: "Generator Room",
    0x06: "Heavy Machinery",
    0x07: "Toxic Waste",
    0x09: "N. Sanity Beach",
    0x0C: "Jungle Rollers",
    0x0E: "Boulders",
    0x0F: "Upstream",
    0x11: "Hog Wild",
    0x12: "The Great Gate",
    0x13: "Boulder Dash",
    0x14: "Road to Nowhere",
    0x15: "Rolling Stones",
    0x16: "The High Road",
    0x18: "Up the Creek",
    0x1A: "Native Fortress",
    0x1C: "Temple Ruins",
    0x1D: "Jaws of Darkness",
    0x1E: "Whole Hog",
    0x20: "The Lost City",
    0x23: "Sunset Vista",
    0x28: "Lights Out",
    0x29: "The Lab",
    0x2A: "Fumbling in the Dark",
    0x2C: "The Great Hall",
    0x2E: "Slippery Climb",
    0x37: "Castle Machinery",
}
BOSSES = {
    0x08: "Pinstripe",
    0x0A: "Papu Papu",
    0x17: "Ripper Roo",
    0x1B: "Dr. Nitrus Brio",
    0x1F: "Dr. Neo Cortex",
    0x21: "Koala Kong",
}
BONUS_ROUNDS = {
    0x24: "a Tawna bonus round",
    0x25: "a Brio bonus round",
    0x33: "a Tawna bonus round",
    0x34: "a Cortex bonus round",
}
UNKNOWN_LEVEL = "an unknown level"
SEPARATOR = " · "


def lookup(name, entries, default):
    lines = [f"Lookup:{name}"]
    lines += [f"0x{key:02X}={text}" for key, text in sorted(entries.items())]
    lines.append(f"*={default}")
    return "\n".join(lines)


def level_is(level_id):
    return f"{LEVEL_ID_ADDRESS}={rcheevos_hex(level_id)}"


def any_level_of(level_ids):
    """Alt groups: true while the level is any of `level_ids` and the core group, if any, holds."""
    return "".join(f"S{level_is(level_id)}" for level_id in sorted(level_ids))


def build_rich_presence():
    """The Crash Bandicoot (USA) script; the first display line whose condition holds is shown."""
    level = f"@Level({LEVEL_ID_ADDRESS})"
    lives = f"@Number({LIVES_VALUE}) @Lives({LIVES_VALUE})"
    wumpa = f"@Number({WUMPA_VALUE}) Wumpa"
    lookups = [
        lookup("Level", {**STAGES, **BOSSES, **BONUS_ROUNDS}, UNKNOWN_LEVEL),
        lookup("Title", TITLE_SCREENS, STARTING_UP),
        "Lookup:Lives\n1=life\n*=lives",
    ]
    display = [
        "Display:",
        f"?{level_is(POWER_ON_LEVEL_ID)}?{STARTING_UP}",
        f"?{level_is(TITLE_LEVEL_ID)}_{TITLE_STATE_ADDRESS}={rcheevos_hex(TITLE_STATE_MAP)}?"
        "On the island map",
        f"?{level_is(TITLE_LEVEL_ID)}?@Title({TITLE_STATE_ADDRESS})",
        f"?{level_is(STAGE_CLEAR_LEVEL_ID)}?On the Stage Clear screen",
        f"?{level_is(INTRO_LEVEL_ID)}?Watching the intro",
        f"?{level_is(ENDING_LEVEL_ID)}?Watching the ending",
        f"?S{DEMO_PLAYBACK_ADDRESS}!=0S{GAME_STATE_ADDRESS}={GAME_STATE_ATTRACT}?"
        f"Watching a demo of {level}",
        f"?{GAME_STATE_ADDRESS}={GAME_STATE_GAME_OVER}?Game Over",
        f"?{LEVEL_SETTLED}{any_level_of(BOSSES)}?Fighting {level}{SEPARATOR}{lives}",
        f"?{any_level_of(BOSSES)}?Fighting {level}",
        f"?{LEVEL_SETTLED}?In {level}{SEPARATOR}{lives}{SEPARATOR}{wumpa}",
        f"In {level}",
    ]
    return "\n\n".join(lookups) + "\n\n" + "\n".join(display) + "\n"


class Command(BaseCommand):
    help = (
        "Seed the Crash Bandicoot 1 rich presence script into Game.rich_presence_patch "
        "(idempotent); an existing script is replaced by the current one."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        game, _author = seed_crash1_game()
        script = build_rich_presence()
        if game.rich_presence_patch == script:
            outcome = "already current"
        else:
            game.rich_presence_patch = script
            game.save(update_fields=["rich_presence_patch"])
            outcome = "updated"
        self.stdout.write(self.style.SUCCESS(f"Crash Bandicoot rich presence {outcome}."))
