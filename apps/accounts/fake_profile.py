"""Placeholder profile data for the PR 22/24 UI work.

None of this is wired to real queries yet — the profile view renders these
stand-ins so the design can be built and reviewed. Real aggregation lands in a
later PR; delete this module then.
"""

# ponytail: placeholder data; real queries land in a later PR.

VALID_TABS = ["overview", "games", "progress", "awards", "wall"]

_HEAT_VALUES = [0, 0, 40, 120, 0, 260, 80, 0, 0, 190, 340, 60, 0, 220]
_HEAT_MAX = 340
_MIN_BAR_PX = 3
_BASE_BAR_PX = 8
_DESKTOP_BAR_SPAN_PX = 74
_MOBILE_BAR_SPAN_PX = 52
_MIN_HEAT_OPACITY = 0.35
_HEAT_OPACITY_SPAN = 0.65
_FULL_OPACITY = "1"


def _heat_bars():
    bars = []
    for value in _HEAT_VALUES:
        if value == 0:
            bars.append(
                {
                    "height": _MIN_BAR_PX,
                    "height_mobile": _MIN_BAR_PX,
                    "opacity": _FULL_OPACITY,
                    "on": False,
                }
            )
        else:
            intensity = value / _HEAT_MAX
            bars.append(
                {
                    "height": _BASE_BAR_PX + round(intensity * _DESKTOP_BAR_SPAN_PX),
                    "height_mobile": _BASE_BAR_PX + round(intensity * _MOBILE_BAR_SPAN_PX),
                    # Formatted here, not in the template: Django localises floats,
                    # so a pt-BR "0,74" would silently break the inline style.
                    "opacity": f"{_MIN_HEAT_OPACITY + intensity * _HEAT_OPACITY_SPAN:.2f}",
                    "on": True,
                }
            )
    return bars


def _consoles():
    raw = [
        {"tag": "∑", "name": "Total", "not_done": 412, "beaten": 96, "plat": 38},
        {"tag": "PS2", "name": "PlayStation 2", "not_done": 88, "beaten": 21, "plat": 9},
        {"tag": "GC", "name": "GameCube", "not_done": 34, "beaten": 12, "plat": 6},
        {"tag": "GBA", "name": "Game Boy Advance", "not_done": 61, "beaten": 15, "plat": 7},
        {"tag": "PS1", "name": "PlayStation", "not_done": 73, "beaten": 18, "plat": 5},
        {"tag": "SNES", "name": "Super Nintendo", "not_done": 52, "beaten": 14, "plat": 8},
        {"tag": "N64", "name": "Nintendo 64", "not_done": 40, "beaten": 9, "plat": 2},
        {"tag": "MD", "name": "Mega Drive", "not_done": 38, "beaten": 5, "plat": 1},
    ]
    out = []
    for console in raw:
        total = console["not_done"] + console["beaten"] + console["plat"]
        out.append(
            {
                **console,
                "total": total,
                "not_pct": f"{console['not_done'] / total * 100:.1f}%",
                "beaten_pct": f"{console['beaten'] / total * 100:.1f}%",
                "plat_pct": f"{console['plat'] / total * 100:.1f}%",
            }
        )
    return out


_DESKTOP_ICON_CAP = 40
_MOBILE_ICON_CELLS = 14
# The mobile strip always keeps one locked cell visible, so it never reads as complete.
_MOBILE_ICON_UNLOCKED_CAP = 13


def _icons(got, cells, total):
    return {
        "cells": [{"unlocked": i < got} for i in range(cells)],
        "more": max(0, total - cells),
    }


def _icon_grids(got, total):
    desktop_cells = min(total, _DESKTOP_ICON_CAP)
    return {
        "grid": _icons(min(got, desktop_cells), desktop_cells, total),
        "grid_mobile": _icons(min(got, _MOBILE_ICON_UNLOCKED_CAP), _MOBILE_ICON_CELLS, total),
    }


def _recent_games():
    raw = [
        {
            "initials": "SQ",
            "title": "Slime Quest VII",
            "state": "beaten",
            "state_label": "BEATEN",
            "meta": "SNES · 34/48 ach · 420/620 pts · 21h played · 6s ago",
            "pct": 71,
            "got": 34,
            "total": 48,
        },
        {
            "initials": "KR",
            "title": "Kart Rumble 64",
            "state": "platinum",
            "state_label": "PLATINUM",
            "meta": "N64 · 48/48 ach · 700/700 pts · 38h played · 2d ago",
            "pct": 100,
            "got": 48,
            "total": 48,
        },
        {
            "initials": "AR",
            "title": "Astral Raiders",
            "state": "progress",
            "state_label": "IN PROGRESS",
            "meta": "PS1 · 12/55 ach · 140/890 pts · 7h played · 5d ago",
            "pct": 22,
            "got": 12,
            "total": 55,
        },
        {
            "initials": "MK",
            "title": "Metro Knights",
            "state": "beaten",
            "state_label": "BEATEN",
            "meta": "GBA · 29/40 ach · 310/500 pts · 15h played · 1w ago",
            "pct": 73,
            "got": 29,
            "total": 40,
        },
        {
            "initials": "TC",
            "title": "Turbo Circuit 99",
            "state": "softcore",
            "state_label": "STARTED",
            "meta": "PS2 · 3/62 ach · 25/950 pts · 2h played · 2w ago",
            "pct": 5,
            "got": 3,
            "total": 62,
        },
    ]
    for game in raw:
        game.update(_icon_grids(game["got"], game["total"]))
    return raw


_COMPLETION_TOTAL = 74


def _completion():
    raw = [
        {"initials": "SQ", "title": "Slime Quest VII", "tag": "SNES", "a": 34, "t": 48},
        {"initials": "KR", "title": "Kart Rumble 64", "tag": "N64", "a": 48, "t": 48},
        {"initials": "AR", "title": "Astral Raiders", "tag": "PS1", "a": 12, "t": 55},
        {"initials": "MK", "title": "Metro Knights", "tag": "GBA", "a": 29, "t": 40},
        {"initials": "TC", "title": "Turbo Circuit 99", "tag": "PS2", "a": 3, "t": 62},
        {"initials": "ZL", "title": "Zephyr Legends", "tag": "GC", "a": 41, "t": 41},
        {"initials": "BM", "title": "Bit Marauder", "tag": "MD", "a": 18, "t": 33},
        {"initials": "FZ", "title": "Fungus Zone", "tag": "GBA", "a": 9, "t": 27},
    ]
    for game in raw:
        game["pct"] = round(game["a"] / game["t"] * 100)
        game["done"] = game["a"] == game["t"]
        game["bar_tone"] = "state-platinum" if game["done"] else "brand"
    return raw


def _game_awards():
    inis = ["SQ", "KR", "MK", "AR", "TC", "ZL", "BM", "FZ"]
    awards = []
    for i in range(24):
        plat = i % 3 == 0
        awards.append(
            {
                "ini": inis[i % len(inis)],
                "tone": "state-platinum" if plat else "gold",
            }
        )
    return awards


def fake_profile_context(user):
    completion = _completion()
    return {
        "profile_user": user,
        "bio": "Platinum hunter since the cartridge days. RPGs and 16-bit platformers.",
        "bio_link": "retroplatinas.log/ph",
        "member_since": "mar/2019",
        "active_ago": "6s",
        "is_hardcore": True,
        "points_total": "138.420",
        "points_weighted": "94.010",
        "rank": "#6.270",
        "rank_total": "152.813",
        "top_pct": "4,10%",
        "last_played": {"initials": "SQ", "title": "Slime Quest VII", "tag": "SNES"},
        "stats": [
            {"label": "Achievements", "value": "4.812", "sub": "unlocked"},
            {"label": "Games beaten", "value": "134", "sub": "98 retail"},
            {"label": "RetroRatio", "value": "1,58", "sub": "weighted/base"},
            {"label": "Started → beaten", "value": "41%", "sub": "rate"},
            {"label": "Points (7d)", "value": "1.240", "sub": "last 7 days"},
            {"label": "Points (30d)", "value": "5.980", "sub": "last 30 days"},
            {"label": "Avg / week", "value": "890", "sub": "pts/week"},
            {"label": "Avg completion", "value": "47%", "sub": "per game"},
            {"label": "Forum posts", "value": "212", "sub": "social"},
            {"label": "Sets requested", "value": "7", "sub": "social"},
        ],
        "heat": _heat_bars(),
        "heat_rate": "1.240 pts / week",
        "recent_games": _recent_games(),
        "consoles": _consoles(),
        "completion": completion,
        "completion_count": _COMPLETION_TOTAL,
        "completion_more": _COMPLETION_TOTAL - len(completion),
        "event_awards": [
            {
                "ini": "AoM",
                "name": "Achievement of the Month",
                "when": "jun/2025",
                "tone": "gold",
            },
            {"ini": "M16", "name": "16-bit Marathon", "when": "mar/2025", "tone": "brand"},
            {"ini": "DC", "name": "Devlog Challenge", "when": "nov/2024", "tone": "state-platinum"},
        ],
        "game_awards": _game_awards(),
        "game_awards_total": 58,
        "game_awards_more": 34,
        "wall": [
            {
                "ini": "MK",
                "name": "MetroKnight",
                "when": "3h ago",
                "text": "Congrats on the Kart Rumble platinum! That final cup was brutal.",
                "owner": False,
            },
            {
                "ini": "PH",
                "name": "PlatinaHunter",
                "when": "2h ago",
                "text": "Thanks! The trick is the stage-3 shortcut. I'll send you the replay.",
                "owner": True,
            },
            {
                "ini": "RS",
                "name": "RetroSofia",
                "when": "1d ago",
                "text": "Your Metro Knights set is saving my life. Really well documented.",
                "owner": False,
            },
        ],
    }
