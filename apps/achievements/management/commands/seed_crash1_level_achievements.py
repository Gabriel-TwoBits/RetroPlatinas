from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.achievements.models import Achievement
from apps.games.models import Console, Game

GAME_TITLE = "Crash Bandicoot"
PS1_RA_ID = 12
IMPORT_AUTHOR = "ra-import"

ACHIEVEMENT_POINTS = 5
RESULTS_SCREEN_RISING_EDGE = "0xH61998=1_d0xH61998=0"
INSIDE_STAGE_GUARD = "0xH61994=0"
CURRENT_STAGE_ADDRESS = "0xH619c5"
STAGE_LOADED_GUARD = "0xW618cc!=0"

LEVEL_ACHIEVEMENTS = [
    ("N. Sanity Beach", 0),
    ("Jungle Rollers", 1),
    ("The Great Gate", 2),
    ("Boulders", 3),
    ("Upstream", 4),
    ("Rolling Stones", 6),
]


def build_mem_addr(stage_id):
    return (
        f"{RESULTS_SCREEN_RISING_EDGE}_{INSIDE_STAGE_GUARD}_"
        f"{CURRENT_STAGE_ADDRESS}={stage_id}_{STAGE_LOADED_GUARD}"
    )


class Command(BaseCommand):
    help = "Seed the first six Crash Bandicoot 1 level-completion achievements (idempotent)."

    def handle(self, *args, **options):
        console, _ = Console.objects.get_or_create(
            ra_id=PS1_RA_ID, defaults={"name": "PlayStation", "short_name": "PS1"}
        )
        game, _ = Game.objects.get_or_create(title=GAME_TITLE, defaults={"console": console})
        author, _ = get_user_model().objects.get_or_create(
            username=IMPORT_AUTHOR, defaults={"is_active": False}
        )

        existing = set(Achievement.objects.filter(game=game).values_list("title", flat=True))
        created = Achievement.objects.bulk_create(
            [
                Achievement(
                    game=game,
                    author=author,
                    title=title,
                    description=f"Complete {title}.",
                    points=ACHIEVEMENT_POINTS,
                    mem_addr=build_mem_addr(stage_id),
                    status=Achievement.STATUS_COMMUNITY,
                )
                for title, stage_id in LEVEL_ACHIEVEMENTS
                if title not in existing
            ]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(created)} level achievements "
                f"({len(LEVEL_ACHIEVEMENTS)} total, {len(existing)} already present)."
            )
        )
