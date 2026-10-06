"""What the feed page shows: the latest unlocks site-wide, refreshed by HTMX polling."""

from apps.core import stats
from apps.images.catalog import avatar_path, badge_path

FEED_UNLOCKS_SHOWN = 50
POLL_SECONDS = 30


def feed_rows():
    """The latest `FEED_UNLOCKS_SHOWN` unlocks of published achievements by active users, newest
    first, each once."""
    # TRADEOFF: no index on unlocked_at and no cache (relative times must stay current), so each
    # poll sorts every unlock; index unlocked_at once the unlock count makes that sort show.
    return [
        {
            "unlock": unlock,
            "avatar_url": avatar_path(unlock.user.username),
            "badge_url": badge_path(unlock.achievement.badge_name),
        }
        for unlock in stats.recent_site_unlocks(FEED_UNLOCKS_SHOWN)
    ]
