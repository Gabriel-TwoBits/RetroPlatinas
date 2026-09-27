"""Rankings, point totals and completion, shared by the API and the site pages.

Only published achievements count. Inactive accounts (system accounts such as `ra-import`,
deactivated users) hold no rank and are left out of player lists and leaderboards.
"""

from typing import NamedTuple

from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, OuterRef, Q

from apps.achievements.models import Achievement, UserUnlock
from apps.games.models import PlayerGame


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


def recent_unlocks(user, limit):
    """The user's latest `limit` unlocks of published achievements, newest first.

    A hardcore unlock writes its softcore twin at the same instant; the twin is left out, so each
    unlock appears once. A softcore unlock earlier than the hardcore one is an unlock of its own.
    """
    hardcore_twin = UserUnlock.objects.filter(
        user=OuterRef("user"),
        achievement=OuterRef("achievement"),
        hardcore=True,
        unlocked_at=OuterRef("unlocked_at"),
    )
    return (
        published_unlocks()
        .filter(user=user)
        .filter(Q(hardcore=True) | ~Exists(hardcore_twin))
        .select_related("achievement__game")
        .order_by("-unlocked_at", "-id")[:limit]
    )


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
