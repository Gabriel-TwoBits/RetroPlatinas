import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.achievements.models import CodeNote
from apps.games.models import Console, Game

GAME_TITLE = "Crash Bandicoot"
PS1_RA_ID = 12
IMPORT_AUTHOR = "ra-import"

CODE_NOTES_PATH = (
    Path(__file__).resolve().parents[3] / "games" / "code-notes" / "crash-bandicoot-1.md"
)
CODE_NOTES_TABLE_HEADING = "## All code notes"
CODE_NOTES_ROW = re.compile(r"^\| `(0x[0-9a-f]+)` \| [^|]* \| (.*) \|$", re.MULTILINE)
CODE_NOTES_ROW_START = re.compile(r"^\| `0x", re.MULTILINE)


def load_code_notes():
    document = CODE_NOTES_PATH.read_text(encoding="utf-8")
    if CODE_NOTES_TABLE_HEADING not in document:
        raise ValueError(f"{CODE_NOTES_PATH} has no '{CODE_NOTES_TABLE_HEADING}' table")

    table = document.split(CODE_NOTES_TABLE_HEADING, 1)[1]
    notes = [
        (address, note.replace("<br>", "\n").replace(r"\|", "|"))
        for address, note in CODE_NOTES_ROW.findall(table)
    ]

    expected = len(CODE_NOTES_ROW_START.findall(table))
    if not expected:
        raise ValueError(f"{CODE_NOTES_PATH} has no code-note rows")
    if len(notes) != expected:
        raise ValueError(
            f"{CODE_NOTES_PATH}: parsed {len(notes)} of {expected} code-note rows — "
            "a row does not match the expected `| \\`0xADDR\\` | type | note |` layout"
        )

    return notes


class Command(BaseCommand):
    help = "Seed the Crash Bandicoot 1 RetroAchievements code notes as CodeNote rows (idempotent)."

    def handle(self, *args, **options):
        code_notes = load_code_notes()
        console, _ = Console.objects.get_or_create(
            ra_id=PS1_RA_ID, defaults={"name": "PlayStation", "short_name": "PS1"}
        )
        game, _ = Game.objects.get_or_create(title=GAME_TITLE, defaults={"console": console})
        author, _ = get_user_model().objects.get_or_create(
            username=IMPORT_AUTHOR, defaults={"is_active": False}
        )

        existing = set(CodeNote.objects.filter(game=game).values_list("address", flat=True))
        created = CodeNote.objects.bulk_create(
            [
                CodeNote(game=game, author=author, address=address, note=note)
                for address, note in code_notes
                if address not in existing
            ]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(created)} code notes "
                f"({len(code_notes)} total, {len(existing)} already present)."
            )
        )
