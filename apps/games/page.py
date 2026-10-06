"""What the public game page and its HTMX tabs show, built from the game's achievements,
leaderboards and sessions."""

from django.utils.translation import gettext_lazy as _

from apps.achievements.models import Achievement, UserUnlock
from apps.core import stats
from apps.images.catalog import avatar_path, badge_path, versioned_game_icon_path

TAB_ACHIEVEMENTS = "achievements"
TAB_LEADERBOARDS = "leaderboards"
TAB_PLAYERS = "players"
TABS = [
    (TAB_ACHIEVEMENTS, _("Achievements")),
    (TAB_LEADERBOARDS, _("Leaderboards")),
    (TAB_PLAYERS, _("Recent players")),
]
VALID_TABS = [slug for slug, _label in TABS]

FILTER_ALL = "all"
FILTER_UNLOCKED = "unlocked"
FILTER_LOCKED = "locked"
FILTERS = [
    (FILTER_ALL, _("All")),
    (FILTER_UNLOCKED, _("Unlocked")),
    (FILTER_LOCKED, _("Locked")),
]
VALID_FILTERS = [slug for slug, _label in FILTERS]
EMPTY_TITLES = {
    FILTER_ALL: _("No published achievements yet"),
    FILTER_UNLOCKED: _("No achievements unlocked yet"),
    FILTER_LOCKED: _("Every achievement unlocked"),
}

# The viewer's state on an achievement; an anonymous visitor's rows carry none.
STATE_HARDCORE = "hardcore"
STATE_SOFTCORE = "softcore"
STATE_LOCKED = "locked"
UNLOCKED_STATES = (STATE_HARDCORE, STATE_SOFTCORE)

# Verified first, as the quality seal, then community; drafts reach only their author.
GROUPS = [
    (Achievement.STATUS_VERIFIED, _("Verified"), "state-platinum"),
    (Achievement.STATUS_COMMUNITY, _("Community"), "brand"),
    (Achievement.STATUS_DRAFT, _("Your drafts"), "gold"),
]

RECENT_PLAYERS_SHOWN = 20


def _unlock_times(game, viewer):
    """`{achievement_id: {"hardcore": unlocked_at, "softcore": unlocked_at}}` of the viewer's
    unlocks in `game`, each mode present only when unlocked in it."""
    if not viewer.is_authenticated:
        return {}
    else:
        times = {}
        for achievement_id, hardcore, unlocked_at in UserUnlock.objects.filter(
            user=viewer, achievement__game=game
        ).values_list("achievement_id", "hardcore", "unlocked_at"):
            mode = STATE_HARDCORE if hardcore else STATE_SOFTCORE
            times.setdefault(achievement_id, {})[mode] = unlocked_at
        return times


def _row(achievement, unlocks, tracked):
    """`unlocks` maps a mode to its unlock time; hardcore outranks the softcore twin it writes."""
    if not tracked:
        state = None
    elif STATE_HARDCORE in unlocks:
        state = STATE_HARDCORE
    elif STATE_SOFTCORE in unlocks:
        state = STATE_SOFTCORE
    else:
        state = STATE_LOCKED
    return {
        "achievement": achievement,
        "state": state,
        "unlocked_at": unlocks.get(state),
        "is_draft": achievement.status == Achievement.STATUS_DRAFT,
        "badge_url": badge_path(achievement.badge_name, locked=state == STATE_LOCKED),
    }


def _achievement_rows(game, viewer):
    """A row per achievement the viewer may see, in the order the emulator receives them."""
    unlock_times = _unlock_times(game, viewer)
    achievements = Achievement.objects.visible_to(viewer).filter(game=game).order_by("id")
    return [
        _row(achievement, unlock_times.get(achievement.pk, {}), viewer.is_authenticated)
        for achievement in achievements
    ]


def _matches(row, achievement_filter):
    unlocked = row["state"] in UNLOCKED_STATES
    if achievement_filter == FILTER_ALL:
        return True
    elif achievement_filter == FILTER_UNLOCKED:
        return unlocked
    elif achievement_filter == FILTER_LOCKED:
        return not unlocked
    else:
        raise ValueError(f"Unknown achievement filter: {achievement_filter}")


def _achievements_panel(rows, achievement_filter):
    shown = [row for row in rows if _matches(row, achievement_filter)]
    groups = [
        {
            "title": title,
            "accent": accent,
            "rows": [row for row in shown if row["achievement"].status == status],
        }
        for status, title, accent in GROUPS
    ]
    # With nothing to filter, every filter is empty for the same reason: the game has no set.
    empty_filter = achievement_filter if rows else FILTER_ALL
    return {
        "achievement_filter": achievement_filter,
        "filters": FILTERS,
        "groups": [group for group in groups if group["rows"]],
        "empty_title": EMPTY_TITLES[empty_filter],
    }


def _leaderboards_panel(game):
    return {"leaderboards": stats.game_leaderboards(game)}


def _players_panel(game):
    return {
        "published_achievements": stats.published_achievement_count(game),
        "players": [
            {"played": played, "avatar_url": avatar_path(played.user.username)}
            for played in stats.game_players_with_progress(game, RECENT_PLAYERS_SHOWN)
        ],
    }


def _frame(game, viewer, tab):
    return {
        "game": game,
        "tab": tab,
        "tabs": TABS,
        "panel_template": f"games/partials/panel-{tab}.html",
        "viewer_tracked": viewer.is_authenticated,
    }


def panel_context(game, viewer, tab, achievement_filter):
    """One tab of the page, for its HTMX swap; `achievement_filter` applies to achievements."""
    if tab == TAB_ACHIEVEMENTS:
        panel = _achievements_panel(_achievement_rows(game, viewer), achievement_filter)
    elif tab == TAB_LEADERBOARDS:
        panel = _leaderboards_panel(game)
    elif tab == TAB_PLAYERS:
        panel = _players_panel(game)
    else:
        raise ValueError(f"Unknown game tab: {tab}")
    return {**_frame(game, viewer, tab), **panel}


def game_context(game, viewer):
    """The full page: the game's header and its achievements tab, unfiltered."""
    rows = _achievement_rows(game, viewer)
    published = [
        row["achievement"]
        for row in rows
        if row["achievement"].status in Achievement.PUBLISHED_STATUSES
    ]
    return {
        **_frame(game, viewer, TAB_ACHIEVEMENTS),
        **_achievements_panel(rows, FILTER_ALL),
        "icon_url": versioned_game_icon_path(game),
        "published_achievements": len(published),
        "published_points": sum(achievement.points for achievement in published),
    }
