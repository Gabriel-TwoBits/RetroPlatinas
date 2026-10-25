from django.core.management.base import BaseCommand
from django.db import transaction

from apps.achievements.management.crash1 import seed_crash1_game, upsert_achievements
from apps.achievements.models import Achievement

ACHIEVEMENT_POINTS = 5
# c1 `cur_lid_ro`: byte 1 of GOOL global 0 (`lid << 8`, set by `GoolInitLid`), the loaded level.
LEVEL_ID_ADDRESS = "0xH6188d"
# c1 `LID_LEVELEND`: the Stage Clear screen, loaded only when a stage is finished.
STAGE_CLEAR_LEVEL_ID = 0x2D
TITLE_LEVEL_ID = 0x19  # title screens, menus, game over screen and island map
# c1 `game_state >> 8`: 3 (`GAME_STATE_CONTINUE`) when a stage is cleared after a death past a
# checkpoint, which skips Stage Clear and loads the map; a quit is 4, a game over 2.
GAME_STATE_ADDRESS = "0xH618d1"
GAME_STATE_LEVEL_WON = 3

# (title, c1 level id), in map order.
LEVEL_ACHIEVEMENTS = [
    ("N. Sanity Beach", 0x09),
    ("Jungle Rollers", 0x0C),
    ("The Great Gate", 0x12),
    ("Boulders", 0x0E),
    ("Upstream", 0x0F),
    ("Rolling Stones", 0x15),
    ("Hog Wild", 0x11),
    ("Native Fortress", 0x1A),
    ("Up the Creek", 0x18),
    ("The Lost City", 0x20),
    ("Temple Ruins", 0x1C),
    ("Road to Nowhere", 0x14),
    ("Boulder Dash", 0x13),
    ("Sunset Vista", 0x23),
    ("Heavy Machinery", 0x06),
    ("Cortex Power", 0x03),
    ("Generator Room", 0x05),
    ("Toxic Waste", 0x07),
    ("The High Road", 0x16),
    ("Slippery Climb", 0x2E),
    ("Lights Out", 0x28),
    ("Jaws of Darkness", 0x1D),
    ("Castle Machinery", 0x37),
    ("The Lab", 0x29),
]


def rcheevos_hex(value):
    """A constant in rcheevos syntax: a bare `0x2d` would be a memory read."""
    return f"h{value:02x}"


def build_mem_addr(level_id):
    """Fires on the frame the loaded level changes from this stage to the Stage Clear screen
    (alt 1), or straight to the map on a clear that skips it (alt 2)."""
    return (
        f"d{LEVEL_ID_ADDRESS}={rcheevos_hex(level_id)}"
        f"S{LEVEL_ID_ADDRESS}={rcheevos_hex(STAGE_CLEAR_LEVEL_ID)}"
        f"S{LEVEL_ID_ADDRESS}={rcheevos_hex(TITLE_LEVEL_ID)}_"
        f"{GAME_STATE_ADDRESS}={GAME_STATE_LEVEL_WON}"
    )


def build_description(title):
    return f"Finish {title}."


class Command(BaseCommand):
    help = (
        "Seed the Crash Bandicoot 1 level-completion achievements (idempotent); "
        "existing rows, matched by title, get the current condition, description and type."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        game, author = seed_crash1_game()

        rows = [
            (
                title,
                build_description(title),
                build_mem_addr(level_id),
                ACHIEVEMENT_POINTS,
                Achievement.TYPE_PROGRESSION,
            )
            for title, level_id in LEVEL_ACHIEVEMENTS
        ]
        created, updated = upsert_achievements(game, author, rows)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(LEVEL_ACHIEVEMENTS)} level achievements: "
                f"{created} created, {updated} updated."
            )
        )
