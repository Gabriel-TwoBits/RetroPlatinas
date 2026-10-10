"""The rows every Crash Bandicoot seed command attaches its data to."""

from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.db import transaction
from django.db.models import Q

from apps.achievements.models import Achievement
from apps.games.forms import SUBSET_GAME_TITLE
from apps.games.models import SET_TYPE_BONUS, Console, Game, GameHash
from apps.leaderboards.models import Leaderboard

GAME_TITLE = "Crash Bandicoot"
PS1_RA_ID = 12
IMPORT_AUTHOR = "ra-import"
# rcheevos PlayStation hash of SCUS-94900, recomputed with rhash; matches the RetroAchievements set.
USA_DISC_MD5 = "35386fd0891e594c9b6d8a4a5baa0027"
USA_DISC_LABEL = "Crash Bandicoot (USA) — SCUS-94900"
# Data, like the achievement titles: the emulator shows it as the subset's name.
BONUS_SET_TITLE = "Bonus"


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


def seed_crash1_bonus_subset(core):
    """Get or create the bonus subset of the Crash Bandicoot core game `core`."""
    subset, _ = Game.objects.get_or_create(
        parent_game=core,
        set_type=SET_TYPE_BONUS,
        set_title=BONUS_SET_TITLE,
        defaults={
            "title": SUBSET_GAME_TITLE.format(parent=core.title, set_title=BONUS_SET_TITLE),
            "console": core.console,
        },
    )
    return subset


def _upsert_by_title(model, noun, game, rows, also_saved=()):
    """Create or update rows of `model` for the set `game`, matched by title among every set of
    its core game; returns `(created, updated)`.

    `rows` holds `(title, fields, create_only)`: `fields` are written on create and brought up to
    date on an existing row, `create_only` only on create. A row found in another set of the game
    moves to `game`, keeping its id. `also_saved` names the columns an update saves besides
    `fields`: `save(update_fields=...)` skips an `auto_now` column otherwise. Raises
    `CommandError`, naming the rows `noun`, on two rows with one title: the caller's transaction
    then writes nothing.
    """
    core = game.core_game
    game_sets = Game.objects.filter(Q(pk=core.pk) | Q(parent_game=core))
    created = updated = 0
    for title, fields, create_only in rows:
        matches = list(model.objects.filter(game__in=game_sets, title=title))
        if not matches:
            model.objects.create(game=game, title=title, **create_only, **fields)
            created += 1
        elif len(matches) == 1:
            row = matches[0]
            current = {"game_id": game.pk, **fields}
            if any(getattr(row, name) != value for name, value in current.items()):
                for name, value in current.items():
                    setattr(row, name, value)
                row.save(update_fields=[*current, *also_saved])
                updated += 1
            else:
                pass  # Already current.
        else:
            raise CommandError(
                f"{len(matches)} {noun} of the sets of {core} are titled {title!r}; "
                "cannot tell which one to update"
            )
    return created, updated


def upsert_achievements(game, author, rows):
    """Create or update the seeded achievements of the set `game`; returns `(created, updated)`.

    `rows` holds `(title, description, mem_addr, points, type)`. A missing title is created as
    `official`; an existing one, matched by title in any set of the game, moves to `game` and gets
    the current condition, description and type while its id, status, points, author and unlocks
    are left alone. Raises `CommandError` on two
    achievements with one title: the caller's transaction then writes nothing.
    """
    return _upsert_by_title(
        Achievement,
        "achievements",
        game,
        [
            (
                title,
                {"mem_addr": mem_addr, "description": description, "type": achievement_type},
                {"author": author, "points": points, "status": Achievement.STATUS_COMMUNITY},
            )
            for title, description, mem_addr, points, achievement_type in rows
        ],
        also_saved=["updated_at"],
    )


def upsert_leaderboards(game, author, rows):
    """Create or update the seeded leaderboards of the set `game`; returns `(created, updated)`.

    `rows` holds `(title, description, mem_addr, format, lower_is_better)`. A missing title is
    created by `author`; an existing one, matched by title in any set of the game, moves to `game`
    and gets the whole current definition, since the format and the ordering only make sense with
    the value its condition measures. Its author and entries are left alone. Raises
    `CommandError` on two leaderboards with one title: the caller's transaction then writes
    nothing.
    """
    return _upsert_by_title(
        Leaderboard,
        "leaderboards",
        game,
        [
            (
                title,
                {
                    "description": description,
                    "mem_addr": mem_addr,
                    "format": value_format,
                    "lower_is_better": lower_is_better,
                },
                {"author": author},
            )
            for title, description, mem_addr, value_format, lower_is_better in rows
        ],
    )
