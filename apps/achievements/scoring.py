from django.contrib.auth import get_user_model
from django.db.models import Max, Min, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.achievements.models import Achievement, UserUnlock
from apps.games.models import PlayerGame

# The achievement fields an unlocker's totals are counted from.
SCORED_FIELDS = frozenset({"status", "points"})


def _official_unlock_points(hardcore):
    points = (
        UserUnlock.objects.filter(
            user=OuterRef("pk"),
            hardcore=hardcore,
            achievement__status=Achievement.STATUS_OFFICIAL,
        )
        .values("user")
        .annotate(total=Sum("achievement__points"))
        .values("total")
    )
    return Coalesce(Subquery(points), 0)


def recalculate_unlocker_points(achievement_ids):
    """Recompute the point totals of everyone who unlocked these achievements from their unlocks.

    Only official unlocks count; unlocks are kept, so an unofficial achievement counts again once
    made official.
    Must run inside a transaction, which holds the lock on the unlockers' rows.
    """
    unlockers = get_user_model().objects.filter(
        pk__in=UserUnlock.objects.filter(achievement_id__in=achievement_ids).values("user_id")
    )
    # handle_awardachievement increments under this row lock, so a concurrent award is not lost.
    list(unlockers.select_for_update().values_list("pk", flat=True))
    unlockers.update(
        softcore_points=_official_unlock_points(hardcore=False),
        hardcore_points=_official_unlock_points(hardcore=True),
    )


def record_unlockers_as_players(unlocks):
    """Give each user of the `UserUnlock` queryset `unlocks` a `PlayerGame` row, spanning those
    unlocks, for every game they unlocked in and have no play record of.

    Rarity divides unlockers by the game's `PlayerGame` rows, so an unlocker without one would
    push it past 100%.
    """
    spans = (
        unlocks.order_by()
        .values("user", "achievement__game")
        .annotate(first_unlock=Min("unlocked_at"), last_unlock=Max("unlocked_at"))
    )
    PlayerGame.objects.bulk_create(
        [
            PlayerGame(
                user_id=span["user"],
                game_id=span["achievement__game"],
                first_played_at=span["first_unlock"],
                last_played_at=span["last_unlock"],
            )
            for span in spans
        ],
        ignore_conflicts=True,
    )
