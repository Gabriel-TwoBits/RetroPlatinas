"""Placeholder home data: static stand-ins the home view renders instead of queries."""

# TRADEOFF: the home shows invented activity and totals; replace with Game/Achievement/UserUnlock
# aggregation and delete this module.


def _numbers():
    return {
        "games": "1",
        "achievements": "38",
        "players": "14",
        "unlocks": "27",
        "online": 2,
    }


def _activity():
    return [
        {
            "initials": "BS",
            "who": "BitSofia",
            "verb": "desbloqueou",
            "ach": "Wumpa Whirlwind",
            "game": "Crash Bandicoot",
            "tag": "PS1",
            "when": "há 2h",
            "hardcore": True,
        },
        {
            "initials": "N9",
            "who": "Naughty95",
            "verb": "zerou",
            "ach": "",
            "game": "Crash Bandicoot",
            "tag": "PS1",
            "when": "há 5h",
            "hardcore": False,
        },
        {
            "initials": "PJ",
            "who": "pixelJoao",
            "verb": "começou",
            "ach": "",
            "game": "Crash Bandicoot",
            "tag": "PS1",
            "when": "há 1d",
            "hardcore": False,
        },
        {
            "initials": "RL",
            "who": "RetroLia",
            "verb": "desbloqueou",
            "ach": "N. Sanity Beach",
            "game": "Crash Bandicoot",
            "tag": "PS1",
            "when": "há 2d",
            "hardcore": True,
        },
    ]


def _sets():
    return [
        {
            "initials": "CB",
            "title": "Crash Bandicoot",
            "tag": "PS1",
            "meta": "38 conquistas · 400 pts · 14 jogadores",
        },
    ]


def fake_home_context():
    return {
        "numbers": _numbers(),
        "activity": _activity(),
        "sets": _sets(),
    }
