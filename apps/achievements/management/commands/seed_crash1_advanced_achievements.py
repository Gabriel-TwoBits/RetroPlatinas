from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.achievements.management.commands.seed_crash1_level_achievements import (
    GAME_STATE_ADDRESS,
    GAME_STATE_LEVEL_WON,
    LEVEL_ID_ADDRESS,
    STAGE_CLEAR_LEVEL_ID,
    TITLE_LEVEL_ID,
    rcheevos_hex,
)
from apps.achievements.management.crash1 import seed_crash1_game, upsert_achievements
from apps.achievements.models import Achievement

# c1 `item_pool1`: the clear gems, one bit per map stage (`0x619c5`), stage n at bit n + 1
# counted from this byte. The Stage Clear screen sets the bit when the box count reached the
# stage's boxes. A death past a checkpoint skips Stage Clear; one before any checkpoint restarts
# the stage with every box back and the count at 0. So the boxes must all go in one run.
GEM_BITS_ADDRESS = 0x61988
BITS_PER_BYTE = 8
# c1 `item_pool2`: the secret stages' gems are not at their bit-per-stage place but here, by map
# cursor, next to the key bits (`0x619ad` bit 2, `0x619ae` bit 4). Measured: the 100% password
# sets `0x619ad` = 05 and `0x619ae` = 14, the keys-only password 04 and 10; which gem is which
# stage comes from the code notes.
SECRET_GEM_BITS = {0x1F: (0x619AD, 0), 0x20: (0x619AE, 2)}
# rcheevos single-bit reads, bit 0 to bit 7 of a byte.
BIT_SIZES = ("0xM", "0xN", "0xO", "0xP", "0xQ", "0xR", "0xS", "0xT")

GEM_POINTS = 10
HARD_GEM_POINTS = 15  # the later stages of the first island and on
# A chase (Boulders, Boulder Dash), a coloured gem in a hard stage (The Lost City, Slippery Climb,
# Lights Out, The Lab), boxes on a later coloured gem's path (Native Fortress and Road to Nowhere:
# red; Boulder Dash: purple), or a stage the community ranks among the hardest (Sunset Vista, The
# High Road), or a secret stage behind a key.
HARDEST_GEM_POINTS = 25

# (title, stage, map cursor `0x619c5`, points), in map order.
GEM_ACHIEVEMENTS = [
    ("Shoreline Sparkle", "N. Sanity Beach", 0x00, GEM_POINTS),
    ("Rolled Clean", "Jungle Rollers", 0x01, GEM_POINTS),
    ("Gatekeeper's Gem", "The Great Gate", 0x02, HARD_GEM_POINTS),
    ("Rock-Solid Gem", "Boulders", 0x03, HARDEST_GEM_POINTS),
    ("Against the Current", "Upstream", 0x04, HARD_GEM_POINTS),
    ("Rubble Rouser", "Rolling Stones", 0x06, HARD_GEM_POINTS),
    ("Hog-Tied Treasure", "Hog Wild", 0x07, HARD_GEM_POINTS),
    ("Fortress Plundered", "Native Fortress", 0x08, HARDEST_GEM_POINTS),
    ("Creek Clearer", "Up the Creek", 0x09, HARD_GEM_POINTS),
    ("Verdant Relic", "The Lost City", 0x0B, HARDEST_GEM_POINTS),
    ("Relic Hunter", "Temple Ruins", 0x0C, HARD_GEM_POINTS),
    ("Somewhere After All", "Road to Nowhere", 0x0D, HARDEST_GEM_POINTS),
    ("Outran the Rock", "Boulder Dash", 0x0E, HARDEST_GEM_POINTS),
    ("Dusk Collector", "Sunset Vista", 0x0F, HARDEST_GEM_POINTS),
    ("Steam Cleaned", "Heavy Machinery", 0x11, HARD_GEM_POINTS),
    ("Power Hoarder", "Cortex Power", 0x12, HARD_GEM_POINTS),
    ("Amber Current", "Generator Room", 0x13, HARD_GEM_POINTS),
    ("Barrels of Blue", "Toxic Waste", 0x14, HARD_GEM_POINTS),
    ("Rope Bridge Riches", "The High Road", 0x16, HARDEST_GEM_POINTS),
    ("Scarlet Summit", "Slippery Climb", 0x17, HARDEST_GEM_POINTS),
    ("Violet After Dark", "Lights Out", 0x18, HARDEST_GEM_POINTS),
    ("Out of the Jaws", "Jaws of Darkness", 0x19, HARD_GEM_POINTS),
    ("Gears and Glitter", "Castle Machinery", 0x1A, HARD_GEM_POINTS),
    ("Golden Experiment", "The Lab", 0x1C, HARDEST_GEM_POINTS),
    ("Found in the Dark", "Fumbling in the Dark", 0x1F, HARDEST_GEM_POINTS),
    ("Whole Hoard", "Whole Hog", 0x20, HARDEST_GEM_POINTS),
]

# Stages whose gem is coloured (community; the code notes agree): every other gem is clear.
COLOURED_GEMS = {
    "The Lost City": "green",
    "Generator Room": "orange",
    "Toxic Waste": "blue",
    "Slippery Climb": "red",
    "Lights Out": "purple",
    "The Lab": "yellow",
}

# A boss fight won goes straight back to the island map, with no Stage Clear screen: the level
# switches from the fight to the title/map level with game state 3 (c1 `GAME_STATE_CONTINUE`). The
# boss's health reaching 0 is not the win: Crash can still die before the fight leaves (Ripper Roo's
# arena keeps exploding TNT after his last hit), and the respawn restarts the fight at full health
# (harness scenario `ripper-roo-death-after-last-hit`).
BOSS_POINTS = 10


@dataclass(frozen=True)
class BossFight:
    title: str
    boss: str
    level_id: int  # c1 `LID_*`
    description: str


BOSS_FIGHTS = (
    BossFight(
        "Chief Toppled",
        "Papu Papu",
        0x0A,
        "Defeat Papu Papu, the tribal chief guarding the way to Rolling Stones.",
    ),
    BossFight(
        "Kangaroo Court",
        "Ripper Roo",
        0x17,
        "Defeat Ripper Roo, the kangaroo guarding the way to The Lost City.",
    ),
    BossFight(
        "Koala Kayo",
        "Koala Kong",
        0x21,
        "Defeat Koala Kong, the muscle-bound koala guarding the way to Cortex's island.",
    ),
    BossFight(
        "Suit Pressed",
        "Pinstripe",
        0x08,
        "Defeat Pinstripe Potoroo in his office at the power plant.",
    ),
    BossFight(
        "Formula Spilled",
        "Dr. Nitrus Brio",
        0x1B,
        "Defeat Dr. Nitrus Brio and the monster his potions make of him.",
    ),
)


def gem_bit_position(map_index):
    """`(address, bit)` of the clear gem of map stage `map_index`, bit 0 the lowest."""
    secret = SECRET_GEM_BITS.get(map_index)
    if secret is not None:
        return secret
    bit = map_index + 1
    return GEM_BITS_ADDRESS + bit // BITS_PER_BYTE, bit % BITS_PER_BYTE


def gem_bit(map_index):
    """The rcheevos bit read of the clear gem of map stage `map_index`."""
    address, bit = gem_bit_position(map_index)
    return f"{BIT_SIZES[bit]}{address:x}"


def build_gem_mem_addr(map_index):
    """Fires on the frame the Stage Clear screen hands out this stage's gem.

    The bit is checked on the Stage Clear level only: a memory card load or a password restores
    gems on the title level, where the edge cannot fire.
    """
    stage_clear = rcheevos_hex(STAGE_CLEAR_LEVEL_ID)
    bit = gem_bit(map_index)
    return "_".join(
        [
            f"{LEVEL_ID_ADDRESS}={stage_clear}",
            f"d{LEVEL_ID_ADDRESS}={stage_clear}",
            f"{bit}=1",
            f"d{bit}=0",
        ]
    )


def build_gem_description(stage):
    colour = COLOURED_GEMS.get(stage, "clear")
    return f"Break every box in {stage} without dying past a checkpoint and win its {colour} gem."


def build_boss_mem_addr(fight):
    """Fires on the frame the boss fight hands over to the island map as won.

    A quit (game state 4), a game over (2) and an attract demo of the fight (6) leave it for the
    same level with another game state; a death respawns inside the fight.
    """
    return (
        f"d{LEVEL_ID_ADDRESS}={rcheevos_hex(fight.level_id)}_"
        f"{LEVEL_ID_ADDRESS}={rcheevos_hex(TITLE_LEVEL_ID)}_"
        f"{GAME_STATE_ADDRESS}={GAME_STATE_LEVEL_WON}"
    )


def advanced_achievements():
    """`(title, description, mem_addr, points, type)` of every advanced achievement."""
    gems = [
        (
            title,
            build_gem_description(stage),
            build_gem_mem_addr(map_index),
            points,
            Achievement.TYPE_NONE,
        )
        for title, stage, map_index, points in GEM_ACHIEVEMENTS
    ]
    bosses = [
        (
            fight.title,
            fight.description,
            build_boss_mem_addr(fight),
            BOSS_POINTS,
            # Every boss bars the way on, so beating it is part of finishing the game.
            Achievement.TYPE_PROGRESSION,
        )
        for fight in BOSS_FIGHTS
    ]
    return [*gems, *bosses]


class Command(BaseCommand):
    help = (
        "Seed the Crash Bandicoot 1 clear gem and boss achievements (idempotent); existing "
        "rows, matched by title, get the current condition, description and type."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        game, author = seed_crash1_game()
        rows = advanced_achievements()
        created, updated = upsert_achievements(game, author, rows)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(rows)} advanced achievements: {created} created, {updated} updated."
            )
        )
