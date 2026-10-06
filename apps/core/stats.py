"""Rankings, point totals, completion and site-wide activity for the stats API, the
`dorequest.php` leaderboard handlers, the profile page and the home page.

Only published achievements count. Inactive accounts (system accounts such as `ra-import`,
deactivated users) hold no rank and are left out of player lists and `leaderboard_entries`; the
leaderboard rank helpers rank whichever entries they are given.
"""

from dataclasses import dataclass
from typing import NamedTuple

from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.achievements.models import Achievement, UserUnlock
from apps.games.models import Game, PlayerGame


class ByMode(NamedTuple):
    """A value per mode. A hardcore unlock also counts as a softcore one, so the softcore value
    covers both modes."""

    hardcore: int | None
    softcore: int | None


def ranked_users():
    return get_user_model().objects.filter(is_active=True)


def published_unlocks():
    return UserUnlock.objects.filter(achievement__status__in=Achievement.PUBLISHED_STATUSES)


def published_achievement_count(game):
    return game.achievements.filter(status__in=Achievement.PUBLISHED_STATUSES).count()


def _global_rank(user, points, users_with_more_points):
    if not user.is_active or points <= 0:
        return None
    else:
        return users_with_more_points + 1


def global_ranks(user):
    """The user's competition rank ("1224") by the points of each mode, `None` in a mode where
    the user has no points or is inactive."""
    with_more_points = ranked_users().aggregate(
        hardcore=Count("pk", filter=Q(hardcore_points__gt=user.hardcore_points)),
        softcore=Count("pk", filter=Q(softcore_points__gt=user.softcore_points)),
    )
    return ByMode(
        hardcore=_global_rank(user, user.hardcore_points, with_more_points["hardcore"]),
        softcore=_global_rank(user, user.softcore_points, with_more_points["softcore"]),
    )


def ranked_player_counts():
    """How many users hold a rank in each mode: active, with points in it."""
    counts = ranked_users().aggregate(
        hardcore=Count("pk", filter=Q(hardcore_points__gt=0)),
        softcore=Count("pk", filter=Q(softcore_points__gt=0)),
    )
    return ByMode(hardcore=counts["hardcore"], softcore=counts["softcore"])


def first_unlocks(user):
    """The user's published unlocks, one per achievement, at its first unlock in any mode.

    A hardcore unlock writes its softcore twin, so the softcore rows are exactly these.
    """
    return published_unlocks().filter(user=user, hardcore=False)


def unlocked_achievement_counts(user):
    """How many distinct published achievements the user unlocked in each mode."""
    counts = (
        published_unlocks()
        .filter(user=user)
        .aggregate(
            hardcore_unlocked=Count("achievement", filter=Q(hardcore=True), distinct=True),
            softcore_unlocked=Count("achievement", filter=Q(hardcore=False), distinct=True),
        )
    )
    return ByMode(hardcore=counts["hardcore_unlocked"], softcore=counts["softcore_unlocked"])


def games_played_count(user):
    return PlayerGame.objects.filter(user=user).count()


def _one_row_per_unlock(unlocks):
    """`unlocks` without the softcore twin a hardcore unlock writes at the same instant, so each
    unlock appears once. A softcore unlock earlier than the hardcore one is an unlock of its own.
    """
    hardcore_twin = UserUnlock.objects.filter(
        user=OuterRef("user"),
        achievement=OuterRef("achievement"),
        hardcore=True,
        unlocked_at=OuterRef("unlocked_at"),
    )
    return unlocks.filter(Q(hardcore=True) | ~Exists(hardcore_twin))


def recent_unlocks(user, limit):
    """The user's latest `limit` unlocks of published achievements, newest first, each once."""
    return (
        _one_row_per_unlock(published_unlocks().filter(user=user))
        .select_related("achievement__game")
        .order_by("-unlocked_at", "-id")[:limit]
    )


def _active_users_unlocks():
    return _one_row_per_unlock(published_unlocks().filter(user__is_active=True))


def site_unlock_count():
    """How many unlocks of published achievements active users made, each once."""
    return _active_users_unlocks().count()


def recent_site_unlocks(limit):
    """The latest `limit` unlocks of published achievements by active users, newest first, each
    once."""
    return (
        _active_users_unlocks()
        .select_related("user", "achievement__game__console")
        .order_by("-unlocked_at", "-id")[:limit]
    )


def published_games():
    """The games with a published achievement, by title, each annotated with
    `published_achievements`, `published_points` and `player_count` (the active users who played
    it)."""
    published = Q(achievements__status__in=Achievement.PUBLISHED_STATUSES)
    # A subquery: counting players through a second join would multiply the achievement sums.
    player_count = (
        PlayerGame.objects.filter(game=OuterRef("pk"), user__is_active=True)
        .order_by()
        .values("game")
        .annotate(count=Count("pk"))
        .values("count")
    )
    return (
        Game.objects.annotate(
            published_achievements=Count("achievements", filter=published),
            published_points=Sum("achievements__points", filter=published),
            player_count=Coalesce(Subquery(player_count), 0),
        )
        .filter(published_achievements__gt=0)
        .select_related("console")
        .order_by("title", "id")
    )


def playing_now():
    """The live sessions of active users, latest ping first."""
    return (
        PlayerGame.objects.playing_now()
        .filter(user__is_active=True)
        .select_related("user", "game__console")
        .order_by("-last_ping_at", "id")
    )


# Unlocking every published achievement of these types beats a game.
BEATING_TYPES = (Achievement.TYPE_PROGRESSION, Achievement.TYPE_WIN_CONDITION)


@dataclass
class GameProgress:
    """A user's progress on one played game's published achievements."""

    played: PlayerGame
    achievements: int
    points: int
    unlocked: ByMode
    points_unlocked: int
    beaten: bool
    platinum: bool


def _game_progress(played, achievements, hardcore_ids, softcore_ids):
    """`achievements` are the game's published `(id, points, type)`; the id sets hold what the
    user unlocked in each mode, softcore covering both."""
    ids = {achievement_id for achievement_id, _, _ in achievements}
    beating_ids = {
        achievement_id
        for achievement_id, _, achievement_type in achievements
        if achievement_type in BEATING_TYPES
    }
    return GameProgress(
        played=played,
        achievements=len(ids),
        points=sum(points for _, points, _ in achievements),
        unlocked=ByMode(hardcore=len(ids & hardcore_ids), softcore=len(ids & softcore_ids)),
        points_unlocked=sum(
            points for achievement_id, points, _ in achievements if achievement_id in softcore_ids
        ),
        beaten=bool(beating_ids) and beating_ids <= softcore_ids,
        platinum=bool(ids) and ids <= hardcore_ids,
    )


def played_games_progress(user):
    """A `GameProgress` for each game the user played, most recently played first.

    A game is beaten once every published progression and win-condition achievement is unlocked
    in any mode, and platinum once every published achievement is unlocked in hardcore.
    """
    played = list(
        PlayerGame.objects.filter(user=user)
        .select_related("game__console")
        .order_by("-last_played_at", "id")
    )
    game_ids = [played_game.game_id for played_game in played]
    achievements_by_game = {game_id: [] for game_id in game_ids}
    for achievement_id, game_id, points, achievement_type in Achievement.objects.filter(
        game_id__in=game_ids, status__in=Achievement.PUBLISHED_STATUSES
    ).values_list("id", "game_id", "points", "type"):
        achievements_by_game[game_id].append((achievement_id, points, achievement_type))
    hardcore_ids = set()
    softcore_ids = set()
    for achievement_id, hardcore in (
        published_unlocks()
        .filter(user=user, achievement__game_id__in=game_ids)
        .values_list("achievement_id", "hardcore")
    ):
        if hardcore:
            hardcore_ids.add(achievement_id)
        else:
            softcore_ids.add(achievement_id)
    return [
        _game_progress(
            played_game, achievements_by_game[played_game.game_id], hardcore_ids, softcore_ids
        )
        for played_game in played
    ]


def _unlocked_in_game(game, hardcore):
    """Counts, on a `PlayerGame`, the distinct published achievements of `game` its user
    unlocked in the mode."""
    return Count(
        "user__unlocks__achievement",
        filter=Q(
            user__unlocks__hardcore=hardcore,
            user__unlocks__achievement__game=game,
            user__unlocks__achievement__status__in=Achievement.PUBLISHED_STATUSES,
        ),
        distinct=True,
    )


def game_players(game):
    """The active users who played `game`, most recently played first."""
    return PlayerGame.objects.filter(game=game, user__is_active=True).order_by(
        "-last_played_at", "id"
    )


def game_players_with_progress(game, limit):
    """The first `limit` of `game_players`, each annotated with `hardcore_unlocked` and
    `softcore_unlocked`: the distinct published achievements of the game its user unlocked."""
    return (
        game_players(game)
        .select_related("user")
        .annotate(
            hardcore_unlocked=_unlocked_in_game(game, hardcore=True),
            softcore_unlocked=_unlocked_in_game(game, hardcore=False),
        )[:limit]
    )


def leaderboard_entries(leaderboard):
    """The leaderboard's entries by active users."""
    return leaderboard.entries.filter(user__is_active=True)


def rank_by_score(entries, lower_is_better, score):
    """Competition rank ("1224") of `score` among the leaderboard `entries`: one more than the
    number of strictly better scores."""
    better = "score__lt" if lower_is_better else "score__gt"
    return entries.filter(**{better: score}).count() + 1


def ranked_entries(entries, lower_is_better, offset, count):
    """`(index, rank, entry)` for `count` of the leaderboard `entries` after the first `offset`,
    best first.

    `index` is the 1-based position on the board; tied scores share the competition rank
    `rank_by_score` gives them.
    """
    order = "score" if lower_is_better else "-score"
    board = entries.select_related("user").order_by(order, "submitted_at", "id")
    ranked = []
    previous_score = None
    previous_rank = None
    for index, entry in enumerate(board[offset : offset + count], start=offset + 1):
        if previous_rank is None:
            rank = rank_by_score(entries, lower_is_better, entry.score)
        elif entry.score == previous_score:
            rank = previous_rank
        else:
            rank = index
        ranked.append((index, rank, entry))
        previous_score = entry.score
        previous_rank = rank
    return ranked
