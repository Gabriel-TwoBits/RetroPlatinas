from django.core.management.base import BaseCommand
from django.db import transaction

from apps.achievements.management.commands.seed_crash1_level_achievements import (
    LEVEL_ACHIEVEMENTS,
    LEVEL_ID_ADDRESS,
    STAGE_CLEAR_LEVEL_ID,
    rcheevos_hex,
)
from apps.achievements.management.commands.seed_crash1_rich_presence import (
    DEMO_PLAYBACK_ADDRESS,
    GAME_STATE_ADDRESS,
    LEVEL_SETTLED,
    PLAYER_LOADED,
    PLAYER_POINTER_ADDRESS,
    TITLE_LEVEL_ID,
)
from apps.achievements.management.crash1 import seed_crash1_game, upsert_achievements

# c1 `game_state >> 8`: 1 while a stage (or a boss fight, a bonus round, an attract demo) plays;
# 5 (`GAME_STATE_NEW_GEM`) from the frame a stage is cleared, gem or not, for about 90 frames.
GAME_STATE_PLAYING = 1
GAME_STATE_STAGE_CLEARED = 5
NO_DEMO = 0  # c1 `pbak_state`: no attract demo picked or playing

# The player object's 24.8 counters, read at their integer byte: Wumpa (+0x160) wraps from 99
# back past 0 and the game adds an extra life; lives (+0x164) are capped at 99.
PLAYER_FRUIT = "0xH161"
PLAYER_LIVES = "0xH165"
MAX_LIVES = 99
# The Aku Aku object (shield level 24.8 at +0x188): one level per mask, the third turns Crash
# invincible for a while.
AKU_POINTER_ADDRESS = "0xW618cc"
AKU_LEVEL = "0xH189"
AKU_INVINCIBLE_LEVEL = 3
# c1 `fruit_count`: the Wumpa count committed when a stage is left (cleared or quit) and handed
# to the player object when the next one starts.
COMMITTED_FRUIT_ADDRESS = "0xH618f5"
NO_WUMPA_STAGE = "N. Sanity Beach"

WUMPA_POINTS = 5
CHALLENGE_POINTS = 10

WUMPA_TITLE = "Fruit Into Life"
AKU_TITLE = "Mask Stack"
LIVES_TITLE = "Bandicoot Reserve"
NO_WUMPA_TITLE = "Beach Diet"


def player_value(offset):
    """A byte of the player object; AddAddress applies the pointer to both sides of a compare."""
    return f"I:{PLAYER_POINTER_ADDRESS}_{offset}"


def aku_value(offset):
    return f"I:{AKU_POINTER_ADDRESS}_{offset}"


def in_play():
    """The player is in control of a stage (not a demo, the title or map, nor Stage Clear), the
    player object has not moved since the previous frame, and the level has held 60 frames.

    Objects hold leftovers of the previous level for a few frames after a level loads, so the
    settle keeps a load from passing for a change of a counter.
    """
    return "_".join(
        [
            f"{GAME_STATE_ADDRESS}={GAME_STATE_PLAYING}",
            f"{DEMO_PLAYBACK_ADDRESS}={NO_DEMO}",
            f"{LEVEL_ID_ADDRESS}!={rcheevos_hex(TITLE_LEVEL_ID)}",
            f"{LEVEL_ID_ADDRESS}!={rcheevos_hex(STAGE_CLEAR_LEVEL_ID)}",
            PLAYER_LOADED,
            f"{PLAYER_POINTER_ADDRESS}=d{PLAYER_POINTER_ADDRESS}",
            LEVEL_SETTLED,
        ]
    )


def build_wumpa_mem_addr():
    """Fires on the frame the player's Wumpa count goes down: it passed 100 and wrapped."""
    return f"{in_play()}_{player_value(PLAYER_FRUIT)}<d{PLAYER_FRUIT}"


def build_lives_mem_addr():
    """Fires on the frame the player's lives rise to the cap.

    TRADEOFF: a 99th life landing after the end of a stage closes `in_play()` is missed until a
    life is lost and earned back; the committed lives (`0x618ed`) could cover it, once measured.
    """
    return (
        f"{in_play()}_"
        f"{player_value(PLAYER_LIVES)}={MAX_LIVES}_"
        f"{player_value(f'd{PLAYER_LIVES}')}<{MAX_LIVES}"
    )


def build_aku_mem_addr():
    """Fires on the frame Aku Aku reaches three masks, from any fewer: two masks can land on one
    game tick."""
    return (
        f"{in_play()}_"
        f"{AKU_POINTER_ADDRESS}=d{AKU_POINTER_ADDRESS}_"
        f"{aku_value(AKU_LEVEL)}={AKU_INVINCIBLE_LEVEL}_"
        f"{aku_value(f'd{AKU_LEVEL}')}<{AKU_INVINCIBLE_LEVEL}"
    )


def build_no_wumpa_mem_addr(level_id):
    """Fires on the frame this stage is cleared while the committed Wumpa count stays as it was
    when the stage started: the clear commits the player's count on that very frame.

    TRADEOFF: exactly 100 Wumpa collected in the run also commits an unchanged count; telling it
    apart needs the lives, which a death changes on the same run.
    """
    return "_".join(
        [
            f"{DEMO_PLAYBACK_ADDRESS}={NO_DEMO}",
            f"{LEVEL_ID_ADDRESS}={rcheevos_hex(level_id)}",
            f"d{GAME_STATE_ADDRESS}={GAME_STATE_PLAYING}",
            f"{GAME_STATE_ADDRESS}={GAME_STATE_STAGE_CLEARED}",
            f"{COMMITTED_FRUIT_ADDRESS}=d{COMMITTED_FRUIT_ADDRESS}",
        ]
    )


def collectible_achievements():
    """`(title, description, mem_addr, points)` of every collectible achievement."""
    no_wumpa_level_id = dict(LEVEL_ACHIEVEMENTS)[NO_WUMPA_STAGE]
    return [
        (
            WUMPA_TITLE,
            "Gather 100 Wumpa fruit and watch them turn into an extra life.",
            build_wumpa_mem_addr(),
            WUMPA_POINTS,
        ),
        (
            AKU_TITLE,
            "Hold three Aku Aku masks at once and become invincible.",
            build_aku_mem_addr(),
            CHALLENGE_POINTS,
        ),
        (
            LIVES_TITLE,
            f"Stock up {MAX_LIVES} lives, the most the game can hold.",
            build_lives_mem_addr(),
            CHALLENGE_POINTS,
        ),
        (
            NO_WUMPA_TITLE,
            f"Finish {NO_WUMPA_STAGE} without picking up a single Wumpa fruit.",
            build_no_wumpa_mem_addr(no_wumpa_level_id),
            CHALLENGE_POINTS,
        ),
    ]


class Command(BaseCommand):
    help = (
        "Seed the Crash Bandicoot 1 Wumpa, lives and Aku Aku achievements (idempotent); "
        "existing rows, matched by title, get the current condition and description."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        game, author = seed_crash1_game()
        rows = collectible_achievements()
        created, updated = upsert_achievements(game, author, rows)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(rows)} collectible achievements: "
                f"{created} created, {updated} updated."
            )
        )
