"""What the feed page shows: the latest unlocks site-wide or of the players the viewer follows,
refreshed by HTMX polling."""

from django.utils.translation import pgettext_lazy

from apps.core import stats
from apps.images.catalog import avatar_path, badge_path

FEED_UNLOCKS_SHOWN = 50
POLL_SECONDS = 30

FILTER_ALL = "all"
FILTER_FRIENDS = "friends"
FILTERS = [
    (FILTER_ALL, pgettext_lazy("feed filter", "All")),
    (FILTER_FRIENDS, pgettext_lazy("feed filter", "Friends")),
]
VALID_FILTERS = [slug for slug, _label in FILTERS]


def _unlocks(feed_filter, viewer):
    if feed_filter == FILTER_FRIENDS:
        return stats.recent_followed_unlocks(viewer, FEED_UNLOCKS_SHOWN)
    elif feed_filter == FILTER_ALL:
        return stats.recent_site_unlocks(FEED_UNLOCKS_SHOWN)
    else:
        raise ValueError(f"Unknown feed filter: {feed_filter}")


def feed_rows(feed_filter, viewer):
    """The latest `FEED_UNLOCKS_SHOWN` unlocks of official achievements by active users (only
    those `viewer` follows under `FILTER_FRIENDS`), newest first, each once."""
    # TRADEOFF: no index on unlocked_at and no cache (relative times must stay current), so each
    # poll sorts every unlock; index unlocked_at once the unlock count makes that sort show.
    return [
        {
            "unlock": unlock,
            "avatar_url": avatar_path(unlock.user.username),
            "badge_url": badge_path(unlock.achievement.badge_name),
        }
        for unlock in _unlocks(feed_filter, viewer)
    ]
