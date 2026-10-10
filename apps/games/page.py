"""What the public game page and its HTMX tabs show, built from the achievements, leaderboards
and sessions of the game's core set and of each of its subsets."""

from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy

from apps.achievements.editing import can_edit
from apps.achievements.models import Achievement, UserUnlock
from apps.comments.threads import thread
from apps.core import stats
from apps.games.models import (
    OPT_IN_SET_TYPES,
    SET_TYPE_BONUS,
    SET_TYPE_CHALLENGE,
    SET_TYPE_EXCLUSIVE,
    SET_TYPE_SPECIALTY,
    GameHash,
    UserSetPreference,
    site_set_order,
)
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

# A set with no achievement is empty under every unlock filter.
EMPTY_TITLES = {
    FILTER_ALL: _("No achievements yet"),
    FILTER_UNLOCKED: _("No achievements unlocked yet"),
    FILTER_LOCKED: _("Every achievement unlocked"),
}

# The viewer's state on an achievement; an anonymous visitor's rows carry none.
STATE_HARDCORE = "hardcore"
STATE_SOFTCORE = "softcore"
STATE_LOCKED = "locked"
UNLOCKED_STATES = (STATE_HARDCORE, STATE_SOFTCORE)

CORE_SET_TITLE = _("Core set")
CORE_SET_EXPLANATION = _("The game's own 100%: everything the game asks of you to finish it.")
SET_TYPE_EXPLANATIONS = {
    SET_TYPE_BONUS: _("Bonus subset: challenges you can take on while playing the game normally."),
    SET_TYPE_CHALLENGE: _("Challenge subset: a specific challenge run, such as a deathless run."),
    SET_TYPE_SPECIALTY: _(
        "Specialty subset: needs a different disc or version of the game, and plays alongside "
        "the core set."
    ),
    SET_TYPE_EXCLUSIVE: _(
        "Exclusive subset: needs a different disc or version of the game, and plays on its own."
    ),
}
# The seal a viewer earns with every official achievement of a set unlocked in hardcore.
CORE_SEAL = _("Platinum")
SUBSET_SEAL = pgettext_lazy("subset seal", "Completed")
CORE_ACCENT = "brand"
CORE_SEAL_TONE = "state-platinum"
SUBSET_ACCENT = "brand2"
PERCENT = 100

RECENT_PLAYERS_SHOWN = 20


def game_sets(game):
    """The core `game` and its subsets, in site order."""
    return sorted([game, *game.subsets.select_related("console")], key=site_set_order)


def _unlock_times(sets, viewer):
    """`{achievement_id: {"hardcore": unlocked_at, "softcore": unlocked_at}}` of the viewer's
    unlocks in `sets`, each mode present only when unlocked in it."""
    if not viewer.is_authenticated:
        return {}
    else:
        times = {}
        for achievement_id, hardcore, unlocked_at in UserUnlock.objects.filter(
            user=viewer, achievement__game__in=sets
        ).values_list("achievement_id", "hardcore", "unlocked_at"):
            mode = STATE_HARDCORE if hardcore else STATE_SOFTCORE
            times.setdefault(achievement_id, {})[mode] = unlocked_at
        return times


def _row(achievement, unlocks, viewer):
    """`unlocks` maps a mode to its unlock time; hardcore outranks the softcore twin it writes."""
    if not viewer.is_authenticated:
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
        "badge_url": badge_path(achievement.badge_name, locked=state == STATE_LOCKED),
        "editable": can_edit(viewer, achievement.author_id),
    }


def _rows_by_set(sets, viewer):
    """`{game_id: rows}`, a row per achievement of each set, in the order the emulator receives
    them."""
    unlock_times = _unlock_times(sets, viewer)
    rows = {set_game.pk: [] for set_game in sets}
    for achievement in Achievement.objects.filter(game__in=sets).order_by("id"):
        rows[achievement.game_id].append(
            _row(achievement, unlock_times.get(achievement.pk, {}), viewer)
        )
    return rows


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


def _official(rows):
    return [row for row in rows if row["achievement"].status == Achievement.STATUS_OFFICIAL]


def _unofficial(rows):
    return [row for row in rows if row["achievement"].status == Achievement.STATUS_UNOFFICIAL]


def _progress(set_game, official_rows, viewer):
    """The viewer's `SetProgress` on the set, `None` for an anonymous visitor."""
    if not viewer.is_authenticated:
        return None
    else:
        hardcore_ids = set()
        softcore_ids = set()
        for row in official_rows:
            if row["state"] == STATE_HARDCORE:
                # A hardcore unlock writes its softcore twin.
                hardcore_ids.add(row["achievement"].pk)
                softcore_ids.add(row["achievement"].pk)
            elif row["state"] == STATE_SOFTCORE:
                softcore_ids.add(row["achievement"].pk)
            else:
                # Locked.
                pass
        official_ids = {row["achievement"].pk for row in official_rows}
        return stats.set_progress(set_game, official_ids, hardcore_ids, softcore_ids)


def _percent(progress):
    """Floored, so 100% means every achievement and never a rounded-up 99.5%."""
    if progress is None or progress.achievements == 0:
        return 0
    else:
        return progress.unlocked.softcore * PERCENT // progress.achievements


def _opted_in_ids(sets, viewer):
    if not viewer.is_authenticated:
        return set()
    else:
        return set(
            UserSetPreference.objects.filter(
                user=viewer, subset_game__in=sets, opted_in=True
            ).values_list("subset_game_id", flat=True)
        )


def _discs(sets):
    """`{game_id: hashes}` of the specialty and exclusive subsets, which load from their own
    discs."""
    discs = {
        set_game.pk: []
        for set_game in sets
        if set_game.set_type in (SET_TYPE_SPECIALTY, SET_TYPE_EXCLUSIVE)
    }
    for game_hash in GameHash.objects.filter(game_id__in=discs).order_by("label", "md5"):
        discs[game_hash.game_id].append(game_hash)
    return discs


def opt_in_context(subset, opted_in):
    """What the opt-in control of a bonus or challenge `subset` shows."""
    return {"subset": subset, "opted_in": opted_in}


def _set_section(set_game, rows, viewer, achievement_filter, opted_in_ids, discs):
    official = _official(rows)
    progress = _progress(set_game, official, viewer)
    shown = [row for row in rows if _matches(row, achievement_filter)]
    if rows:
        empty_title = EMPTY_TITLES[achievement_filter]
    else:
        empty_title = EMPTY_TITLES[FILTER_ALL]
    if set_game.is_subset:
        identity = {
            "title": set_game.set_title,
            "accent": SUBSET_ACCENT,
            "explanation": SET_TYPE_EXPLANATIONS[set_game.set_type],
            "seal": SUBSET_SEAL,
            "seal_tone": SUBSET_ACCENT,
        }
    else:
        identity = {
            "title": CORE_SET_TITLE,
            "accent": CORE_ACCENT,
            "explanation": CORE_SET_EXPLANATION,
            "seal": CORE_SEAL,
            "seal_tone": CORE_SEAL_TONE,
        }
    if set_game.set_type in OPT_IN_SET_TYPES:
        opt_in = opt_in_context(set_game, set_game.pk in opted_in_ids)
    else:
        opt_in = None
    return {
        **identity,
        "game": set_game,
        "official_rows": _official(shown),
        "unofficial_rows": _unofficial(shown),
        "empty_title": empty_title,
        "official_achievements": len(official),
        "official_points": sum(row["achievement"].points for row in official),
        "progress": progress,
        "percent": _percent(progress),
        "opt_in": opt_in,
        "discs": discs.get(set_game.pk),
    }


def _achievements_panel(sets, rows_by_set, viewer, achievement_filter):
    opted_in_ids = _opted_in_ids(sets, viewer)
    discs = _discs(sets)
    return {
        "achievement_filter": achievement_filter,
        "filters": FILTERS,
        "sets": [
            _set_section(
                set_game,
                rows_by_set[set_game.pk],
                viewer,
                achievement_filter,
                opted_in_ids,
                discs,
            )
            for set_game in sets
        ],
    }


def _leaderboards_panel(sets):
    order = {set_game.pk: index for index, set_game in enumerate(sets)}
    leaderboards = stats.game_leaderboards(sets).select_related("game")
    return {
        "leaderboards": sorted(
            leaderboards, key=lambda leaderboard: (order[leaderboard.game_id], leaderboard.pk)
        )
    }


def _players_panel(game):
    return {
        "official_achievements": stats.official_achievement_count(game),
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
    """One tab of the core `game`'s page, for its HTMX swap; `achievement_filter` applies to
    achievements."""
    sets = game_sets(game)
    if tab == TAB_ACHIEVEMENTS:
        panel = _achievements_panel(sets, _rows_by_set(sets, viewer), viewer, achievement_filter)
    elif tab == TAB_LEADERBOARDS:
        panel = _leaderboards_panel(sets)
    elif tab == TAB_PLAYERS:
        panel = _players_panel(game)
    else:
        raise ValueError(f"Unknown game tab: {tab}")
    return {**_frame(game, viewer, tab), **panel}


def game_context(game, viewer):
    """The core `game`'s full page: its header with the core set's totals, its achievements tab
    unfiltered, and its comments."""
    sets = game_sets(game)
    rows_by_set = _rows_by_set(sets, viewer)
    official = _official(rows_by_set[game.pk])
    return {
        **_frame(game, viewer, TAB_ACHIEVEMENTS),
        **_achievements_panel(sets, rows_by_set, viewer, FILTER_ALL),
        "icon_url": versioned_game_icon_path(game),
        "official_achievements": len(official),
        "official_points": sum(row["achievement"].points for row in official),
        "can_add_subsets": viewer.is_staff,
        "thread": thread(game, viewer),
    }
