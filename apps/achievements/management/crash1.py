"""The rows every Crash Bandicoot seed command attaches its data to."""

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.db import transaction

from apps.achievements.models import Achievement
from apps.games.models import Console, Game, GameHash
from apps.leaderboards.models import Leaderboard

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


def upsert_achievements(game, author, rows):
    """Create or update the seeded achievements of `game`; returns `(created, updated)`.

    `rows` holds `(title, description, mem_addr, points)`. A missing title is created as
    `community`; an existing one, matched by title, gets the current condition and description
    while its status, points, author and unlocks are left alone. Raises `CommandError` on two
    achievements with one title: the caller's transaction then writes nothing.
    """
    created = updated = 0
    for title, description, mem_addr, points in rows:
        fields = {"mem_addr": mem_addr, "description": description}
        matches = list(Achievement.objects.filter(game=game, title=title))
        if not matches:
            Achievement.objects.create(
                game=game,
                author=author,
                title=title,
                points=points,
                status=Achievement.STATUS_COMMUNITY,
                **fields,
            )
            created += 1
        elif len(matches) == 1:
            row = matches[0]
            if any(getattr(row, name) != value for name, value in fields.items()):
                for name, value in fields.items():
                    setattr(row, name, value)
                row.save(update_fields=[*fields, "updated_at"])
                updated += 1
            else:
                pass  # Already current.
        else:
            raise CommandError(
                f"{len(matches)} achievements of {game} are titled {title!r}; "
                "cannot tell which one to update"
            )
    return created, updated


def upsert_leaderboards(game, rows):
    """Create or update the seeded leaderboards of `game`; returns `(created, updated)`.

    `rows` holds `(title, description, mem_addr, format, lower_is_better)`. A missing title is
    created; an existing one, matched by title, gets the whole current definition, since the
    format and the ordering only make sense with the value its condition measures. Its entries
    are left alone. Raises `CommandError` on two leaderboards with one title: the caller's
    transaction then writes nothing.
    """
    created = updated = 0
    for title, description, mem_addr, value_format, lower_is_better in rows:
        fields = {
            "description": description,
            "mem_addr": mem_addr,
            "format": value_format,
            "lower_is_better": lower_is_better,
        }
        matches = list(Leaderboard.objects.filter(game=game, title=title))
        if not matches:
            Leaderboard.objects.create(game=game, title=title, **fields)
            created += 1
        elif len(matches) == 1:
            row = matches[0]
            if any(getattr(row, name) != value for name, value in fields.items()):
                for name, value in fields.items():
                    setattr(row, name, value)
                row.save(update_fields=list(fields))
                updated += 1
            else:
                pass  # Already current.
        else:
            raise CommandError(
                f"{len(matches)} leaderboards of {game} are titled {title!r}; "
                "cannot tell which one to update"
            )
    return created, updated
