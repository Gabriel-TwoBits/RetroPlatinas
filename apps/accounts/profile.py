"""What the profile page and its mobile panels show, built from the user's unlocks and sessions."""

from collections import defaultdict
from datetime import timedelta

from django.contrib.humanize.templatetags.humanize import intcomma, naturaltime
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from apps.core import stats
from apps.games.models import PlayerGame
from apps.images.catalog import avatar_path, badge_path

VALID_TABS = ["overview", "awards", "games", "progress"]

RECENT_UNLOCKS_SHOWN = 20
RECENT_GAMES_SHOWN = 5
AWARDS_SHOWN = 24
DESKTOP_ICON_CELLS = 40
MOBILE_ICON_CELLS = 14
INITIALS_LETTERS = 2
TOTAL_TAG = "∑"
SECONDS_PER_MINUTE = int(timedelta(minutes=1).total_seconds())
SECONDS_PER_HOUR = int(timedelta(hours=1).total_seconds())

SHORT_WINDOW = timedelta(days=7)
LONG_WINDOW = timedelta(days=30)
ONE_WEEK = timedelta(weeks=1)
HEAT_DAYS = 14

_MIN_BAR_PX = 3
_BASE_BAR_PX = 8
_DESKTOP_BAR_SPAN_PX = 74
_MOBILE_BAR_SPAN_PX = 52
_MIN_HEAT_OPACITY = 0.35
_HEAT_OPACITY_SPAN = 0.65
_FULL_OPACITY = "1"
_PERCENT = 100

STATE_PLATINUM = "platinum"
STATE_BEATEN = "beaten"
STATE_PROGRESS = "progress"
STATE_LABELS = {
    STATE_PLATINUM: _("Platinum"),
    STATE_BEATEN: _("Beaten"),
    STATE_PROGRESS: _("In progress"),
}


def _initials(title):
    words = title.split()
    return "".join(word[0] for word in words[:INITIALS_LETTERS]).upper()


def _percent(part, whole):
    """Floored, so 100% means every achievement and never a rounded-up 99.5%."""
    if whole == 0:
        return 0
    else:
        return part * _PERCENT // whole


def _css_percent(part, whole):
    """A CSS width, formatted in Python: Django would localise a float to a pt-BR `12,5`."""
    if whole == 0:
        return "0%"
    else:
        return f"{part / whole * _PERCENT:.1f}%"


def _state(progress):
    if progress.platinum:
        return STATE_PLATINUM
    elif progress.beaten:
        return STATE_BEATEN
    else:
        return STATE_PROGRESS


def _playtime(seconds):
    hours = seconds // SECONDS_PER_HOUR
    if hours > 0:
        return gettext("%(hours)s h") % {"hours": hours}
    else:
        return gettext("%(minutes)s min") % {"minutes": seconds // SECONDS_PER_MINUTE}


def _meta(progress):
    played = progress.played
    return gettext(
        "%(console)s · %(unlocked)s/%(total)s achievements (%(hardcore)s hardcore) · "
        "%(points_unlocked)s/%(points)s pts · %(playtime)s played · %(when)s"
    ) % {
        "console": played.game.console.short_name,
        "unlocked": progress.unlocked.softcore,
        "total": progress.achievements,
        "hardcore": progress.unlocked.hardcore,
        "points_unlocked": intcomma(progress.points_unlocked),
        "points": intcomma(progress.points),
        "playtime": _playtime(played.playtime_seconds),
        "when": naturaltime(played.last_played_at),
    }


def _icons(unlocked, total, cap):
    cells = min(total, cap)
    return {
        "cells": [{"unlocked": index < unlocked} for index in range(cells)],
        "more": total - cells,
    }


def _game(progress):
    game = progress.played.game
    state = _state(progress)
    return {
        "game": game,
        "played": progress.played,
        "initials": _initials(game.title),
        "tag": game.console.short_name,
        "achievements": progress.achievements,
        "points": progress.points,
        "unlocked": progress.unlocked,
        "points_unlocked": progress.points_unlocked,
        "meta": _meta(progress),
        "pct": _percent(progress.unlocked.softcore, progress.achievements),
        "beaten": progress.beaten,
        "state": state,
        "state_label": STATE_LABELS[state],
        "grid": _icons(progress.unlocked.softcore, progress.achievements, DESKTOP_ICON_CELLS),
        "grid_mobile": _icons(progress.unlocked.softcore, progress.achievements, MOBILE_ICON_CELLS),
    }


def _console_row(tag, name, games):
    platinum = sum(1 for game in games if game["state"] == STATE_PLATINUM)
    beaten = sum(1 for game in games if game["state"] == STATE_BEATEN)
    not_done = len(games) - platinum - beaten
    return {
        "tag": tag,
        "name": name,
        "total": len(games),
        "not_done": not_done,
        "beaten": beaten,
        "plat": platinum,
        "not_pct": _css_percent(not_done, len(games)),
        "beaten_pct": _css_percent(beaten, len(games)),
        "plat_pct": _css_percent(platinum, len(games)),
    }


def _consoles(games):
    """The total row first, then one row per console, most played first; none without games."""
    if not games:
        return []
    else:
        by_console = defaultdict(list)
        for game in games:
            by_console[game["game"].console].append(game)
        ordered = sorted(by_console.items(), key=lambda item: (-len(item[1]), item[0].name))
        return [_console_row(TOTAL_TAG, _("Total"), games)] + [
            _console_row(console.short_name, console.name, console_games)
            for console, console_games in ordered
        ]


def _awards(games):
    """Platinums first, then beaten games, each in the order the games were last played."""
    platinums = [game for game in games if game["state"] == STATE_PLATINUM]
    beaten = [game for game in games if game["state"] == STATE_BEATEN]
    return [{**game, "tone": "state-platinum"} for game in platinums] + [
        {**game, "tone": "state-beaten"} for game in beaten
    ]


def _heat_opacity(intensity):
    return f"{_MIN_HEAT_OPACITY + intensity * _HEAT_OPACITY_SPAN:.2f}"


def _heat_bar(points, peak):
    if points == 0:
        return {
            "height": _MIN_BAR_PX,
            "height_mobile": _MIN_BAR_PX,
            "opacity": _FULL_OPACITY,
            "on": False,
        }
    else:
        intensity = points / peak
        return {
            "height": _BASE_BAR_PX + round(intensity * _DESKTOP_BAR_SPAN_PX),
            "height_mobile": _BASE_BAR_PX + round(intensity * _MOBILE_BAR_SPAN_PX),
            "opacity": _heat_opacity(intensity),
            "on": True,
        }


def _heat(points_by_day, today):
    """A bar per day of the last `HEAT_DAYS`, today last, its height and opacity by the points
    earned that day."""
    days = [today - timedelta(days=offset) for offset in reversed(range(HEAT_DAYS))]
    values = [points_by_day.get(day, 0) for day in days]
    peak = max(values)
    return [_heat_bar(points, peak) for points in values], sum(values)


def _average_completion(games):
    with_achievements = [game["pct"] for game in games if game["achievements"]]
    if not with_achievements:
        return None
    else:
        return sum(with_achievements) // len(with_achievements)


def _points_per_week(user, now):
    weeks = max((now - user.date_joined) / ONE_WEEK, 1)
    return round(user.softcore_points / weeks)


def _activity(user, now):
    """Points earned (first unlocks, any mode) in the short and long windows, and per local
    day."""
    recent = stats.first_unlocks(user).filter(unlocked_at__gte=now - LONG_WINDOW)
    short_window_points = 0
    long_window_points = 0
    points_by_day = defaultdict(int)
    for unlocked_at, points in recent.values_list("unlocked_at", "achievement__points"):
        long_window_points += points
        if unlocked_at >= now - SHORT_WINDOW:
            short_window_points += points
        points_by_day[timezone.localtime(unlocked_at).date()] += points
    return short_window_points, long_window_points, points_by_day


def _current_game(user, games):
    """The live session, else the game played last, else `None`."""
    live = (
        PlayerGame.objects.playing_now()
        .filter(user=user)
        .select_related("game__console")
        .order_by("-last_ping_at")
        .first()
    )
    if live is not None:
        return {"played": live, "initials": _initials(live.game.title), "live": True}
    elif games:
        return {"played": games[0]["played"], "initials": games[0]["initials"], "live": False}
    else:
        return None


def _recent_unlocks(user):
    return [
        {"unlock": unlock, "badge_url": badge_path(unlock.achievement.badge_name)}
        for unlock in stats.recent_unlocks(user, RECENT_UNLOCKS_SHOWN)
    ]


def profile_context(profile_user, viewer):
    now = timezone.now()
    games = [_game(progress) for progress in stats.played_games_progress(profile_user)]
    awards = _awards(games)
    short_window_points, long_window_points, points_by_day = _activity(profile_user, now)
    heat, heat_points = _heat(points_by_day, timezone.localdate(now))
    return {
        "profile_user": profile_user,
        "is_owner": viewer.is_authenticated and viewer.pk == profile_user.pk,
        "avatar_url": avatar_path(profile_user.username),
        "points": stats.ByMode(profile_user.hardcore_points, profile_user.softcore_points),
        "ranks": stats.global_ranks(profile_user),
        "ranked_players": stats.ranked_player_counts(),
        "unlocked": stats.unlocked_achievement_counts(profile_user),
        "current_game": _current_game(profile_user, games),
        "games_played": len(games),
        "games_beaten": sum(1 for game in games if game["beaten"]),
        "platinums": sum(1 for game in games if game["state"] == STATE_PLATINUM),
        "average_completion": _average_completion(games),
        "short_window_days": SHORT_WINDOW.days,
        "long_window_days": LONG_WINDOW.days,
        "points_short_window": short_window_points,
        "points_long_window": long_window_points,
        "points_per_week": _points_per_week(profile_user, now),
        "heat": heat,
        # The bars run from `HEAT_DAYS - 1` days ago to today.
        "heat_oldest_days_ago": HEAT_DAYS - 1,
        "heat_points": heat_points,
        "recent_unlocks": _recent_unlocks(profile_user),
        "recent_games": games[:RECENT_GAMES_SHOWN],
        # TRADEOFF: every played game, unpaginated; page it if players reach hundreds of games.
        "completion": games,
        "consoles": _consoles(games),
        "awards": awards[:AWARDS_SHOWN],
        "awards_more": max(len(awards) - AWARDS_SHOWN, 0),
    }
