from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.achievements.management.crash1 import seed_crash1_game
from apps.achievements.models import Achievement

ACHIEVEMENT_POINTS = 5
# c1 `cur_lid_ro`: byte 1 of GOOL global 0 (`lid << 8`, set by `GoolInitLid`), the loaded level.
LEVEL_ID_ADDRESS = "0xH6188d"
# c1 `LID_LEVELEND`: the Stage Clear screen, loaded only when a stage is finished.
STAGE_CLEAR_LEVEL_ID = 0x2D

# (title, c1 level id), in map order.
LEVEL_ACHIEVEMENTS = [
    ("N. Sanity Beach", 0x09),
    ("Jungle Rollers", 0x0C),
    ("The Great Gate", 0x12),
    ("Boulders", 0x0E),
    ("Upstream", 0x0F),
    ("Rolling Stones", 0x15),
]


def rcheevos_hex(value):
    """A constant in rcheevos syntax: a bare `0x2d` would be a memory read."""
    return f"h{value:02x}"


def build_mem_addr(level_id):
    """Fires on the frame the loaded level changes from this stage to the Stage Clear screen."""
    return (
        f"{LEVEL_ID_ADDRESS}={rcheevos_hex(STAGE_CLEAR_LEVEL_ID)}_"
        f"d{LEVEL_ID_ADDRESS}={rcheevos_hex(level_id)}"
    )


def build_description(title):
    return f"Finish {title} and reach the Stage Clear screen."


class Command(BaseCommand):
    help = (
        "Seed the first six Crash Bandicoot 1 level-completion achievements (idempotent); "
        "existing rows, matched by title, get the current condition and description."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        game, author = seed_crash1_game()

        created = updated = 0
        for title, level_id in LEVEL_ACHIEVEMENTS:
            fields = {"mem_addr": build_mem_addr(level_id), "description": build_description(title)}
            rows = list(Achievement.objects.filter(game=game, title=title))
            if not rows:
                Achievement.objects.create(
                    game=game,
                    author=author,
                    title=title,
                    points=ACHIEVEMENT_POINTS,
                    status=Achievement.STATUS_COMMUNITY,
                    **fields,
                )
                created += 1
            elif len(rows) == 1:
                row = rows[0]
                if any(getattr(row, name) != value for name, value in fields.items()):
                    for name, value in fields.items():
                        setattr(row, name, value)
                    row.save(update_fields=[*fields, "updated_at"])
                    updated += 1
                else:
                    pass  # Already current.
            else:
                raise CommandError(
                    f"{len(rows)} achievements of {game} are titled {title!r}; "
                    "cannot tell which one to update"
                )
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(LEVEL_ACHIEVEMENTS)} level achievements: "
                f"{created} created, {updated} updated."
            )
        )
