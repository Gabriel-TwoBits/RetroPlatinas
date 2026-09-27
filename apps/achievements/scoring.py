from django.contrib.auth import get_user_model
from django.db.models import OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.achievements.models import Achievement, UserUnlock


def _published_unlock_points(hardcore):
    points = (
        UserUnlock.objects.filter(
            user=OuterRef("pk"),
            hardcore=hardcore,
            achievement__status__in=Achievement.PUBLISHED_STATUSES,
        )
        .values("user")
        .annotate(total=Sum("achievement__points"))
        .values("total")
    )
    return Coalesce(Subquery(points), 0)


def recalculate_unlocker_points(achievement_ids):
    """Recompute the point totals of everyone who unlocked these achievements from their unlocks.

    Only published unlocks count; unlocks are kept, so a draft counts again once republished.
    Must run inside a transaction, which holds the lock on the unlockers' rows.
    """
    unlockers = get_user_model().objects.filter(
        pk__in=UserUnlock.objects.filter(achievement_id__in=achievement_ids).values("user_id")
    )
    # handle_awardachievement increments under this row lock, so a concurrent award is not lost.
    list(unlockers.select_for_update().values_list("pk", flat=True))
    unlockers.update(
        softcore_points=_published_unlock_points(hardcore=False),
        hardcore_points=_published_unlock_points(hardcore=True),
    )
