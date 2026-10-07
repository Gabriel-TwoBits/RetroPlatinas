from django.core.management.base import BaseCommand
from django.db import transaction

from apps.achievements.management.commands.seed_crash1_collectible_achievements import in_play
from apps.achievements.management.commands.seed_crash1_level_achievements import (
    LEVEL_ID_ADDRESS,
    STAGE_CLEAR_LEVEL_ID,
    rcheevos_hex,
)
from apps.achievements.management.crash1 import seed_crash1_game, upsert_achievements

# c1 `item_pool1`: the clear gems, one bit per map stage (`0x619c5`), stage n at bit n + 1
# counted from this byte. The Stage Clear screen sets the bit when the box count reached the
# stage's boxes; a death sets the count back to 0, so the boxes must all go in one life.
GEM_BITS_ADDRESS = 0x61988
BITS_PER_BYTE = 8
# rcheevos single-bit reads, bit 0 to bit 7 of a byte.
BIT_SIZES = ("0xM", "0xN", "0xO", "0xP", "0xQ", "0xR", "0xS", "0xT")

GEM_POINTS = 10
HARD_GEM_POINTS = 15  # the later stages of the first island
CHASE_GEM_POINTS = 25  # Boulders: every box broken while the boulder rolls after Crash

# (title, stage, map cursor `0x619c5`, points), in map order.
GEM_ACHIEVEMENTS = [
    ("Shoreline Sparkle", "N. Sanity Beach", 0x00, GEM_POINTS),
    ("Rolled Clean", "Jungle Rollers", 0x01, GEM_POINTS),
    ("Gatekeeper's Gem", "The Great Gate", 0x02, HARD_GEM_POINTS),
    ("Rock-Solid Gem", "Boulders", 0x03, CHASE_GEM_POINTS),
    ("Against the Current", "Upstream", 0x04, HARD_GEM_POINTS),
]

# The boss object of a boss fight, reallocated on every respawn; the integer byte of its 24.8
# health at +0x104. Papu Papu starts at 3 and loses one per hit; the fight then goes straight
# back to the island map, with no Stage Clear screen.
BOSS_POINTER_ADDRESS = "0xW60ddc"
BOSS_HEALTH = "0xH105"
PAPU_PAPU_LEVEL_ID = 0x0A  # c1 `LID_*`
LAST_HIT_HEALTH = 1
BOSS_POINTS = 10
BOSS_TITLE = "Chief Toppled"
BOSS_NAME = "Papu Papu"


def gem_bit_position(map_index):
    """`(address, bit)` of the clear gem of map stage `map_index`, bit 0 the lowest."""
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
    return f"Break every box in {stage} without losing a life and win its clear gem."


def boss_value(offset):
    """A byte of the boss object; AddAddress applies the pointer to both sides of a compare."""
    return f"I:{BOSS_POINTER_ADDRESS}_{offset}"


def build_boss_mem_addr(level_id):
    """Fires on the frame the boss of this fight loses its last health, the boss object unchanged
    since the previous frame (a respawn allocates a new one at full health)."""
    return "_".join(
        [
            in_play(),
            f"{LEVEL_ID_ADDRESS}={rcheevos_hex(level_id)}",
            f"{BOSS_POINTER_ADDRESS}!=0",
            f"{BOSS_POINTER_ADDRESS}=d{BOSS_POINTER_ADDRESS}",
            f"{boss_value(BOSS_HEALTH)}=0",
            f"{boss_value(f'd{BOSS_HEALTH}')}={LAST_HIT_HEALTH}",
        ]
    )


def advanced_achievements():
    """`(title, description, mem_addr, points)` of every advanced achievement."""
    gems = [
        (title, build_gem_description(stage), build_gem_mem_addr(map_index), points)
        for title, stage, map_index, points in GEM_ACHIEVEMENTS
    ]
    boss = (
        BOSS_TITLE,
        f"Defeat {BOSS_NAME}, the tribal chief guarding the way to Rolling Stones.",
        build_boss_mem_addr(PAPU_PAPU_LEVEL_ID),
        BOSS_POINTS,
    )
    return [*gems, boss]


class Command(BaseCommand):
    help = (
        "Seed the Crash Bandicoot 1 clear gem and boss achievements (idempotent); existing "
        "rows, matched by title, get the current condition and description."
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
