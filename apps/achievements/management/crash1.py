"""The rows every Crash Bandicoot seed command attaches its data to."""

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.db import transaction

from apps.games.models import Console, Game, GameHash

GAME_TITLE = "Crash Bandicoot"
PS1_RA_ID = 12
IMPORT_AUTHOR = "ra-import"
# rcheevos PlayStation hash of SCUS-94900, recomputed with rhash; matches the RetroAchievements set.
USA_DISC_MD5 = "35386fd0891e594c9b6d8a4a5baa0027"
USA_DISC_LABEL = "Crash Bandicoot (USA) — SCUS-94900"


@transaction.atomic
def seed_crash1_game():
    """Get or create the Crash Bandicoot game (console, USA disc hash) and the import author.

    Returns `(game, author)`. Raises `CommandError`, creating nothing, when the hash belongs to
    another game: `gameid` would resolve the disc to a game without the seeded rows.
    """
    console, _ = Console.objects.get_or_create(
        ra_id=PS1_RA_ID, defaults={"name": "PlayStation", "short_name": "PS1"}
    )
    game, _ = Game.objects.get_or_create(title=GAME_TITLE, defaults={"console": console})
    disc_hash, _ = GameHash.objects.get_or_create(
        md5=USA_DISC_MD5, defaults={"game": game, "label": USA_DISC_LABEL}
    )
    if disc_hash.game_id != game.pk:
        raise CommandError(
            f"GameHash {USA_DISC_MD5} belongs to game {disc_hash.game_id} ({disc_hash.game}), "
            f"not to {GAME_TITLE!r} (game {game.pk})"
        )
    author, _ = get_user_model().objects.get_or_create(
        username=IMPORT_AUTHOR, defaults={"is_active": False}
    )
    return game, author
