"""The rows every Crash Bandicoot seed command attaches its data to."""

from django.contrib.auth import get_user_model

from apps.games.models import Console, Game

GAME_TITLE = "Crash Bandicoot"
PS1_RA_ID = 12
IMPORT_AUTHOR = "ra-import"


def seed_crash1_game():
    """Get or create the PlayStation console, the Crash Bandicoot game and the import author.

    Returns ``(game, author)``.
    """
    console, _ = Console.objects.get_or_create(
        ra_id=PS1_RA_ID, defaults={"name": "PlayStation", "short_name": "PS1"}
    )
    game, _ = Game.objects.get_or_create(title=GAME_TITLE, defaults={"console": console})
    author, _ = get_user_model().objects.get_or_create(
        username=IMPORT_AUTHOR, defaults={"is_active": False}
    )
    return game, author
