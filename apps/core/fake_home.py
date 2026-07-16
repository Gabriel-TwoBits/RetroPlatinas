"""Placeholder home data for the PR 22 landing page.

Not wired to real queries yet — the home view renders these stand-ins so the
design can be built and reviewed. Real aggregation lands in a later PR; delete
this module then.
"""


def _numbers():
    return {
        "games": "1",
        "achievements": "38",
        "players": "14",
        "unlocks": "27",
        # An int, so the template can branch on "anyone online?" instead of on a dash.
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
            "hot": True,
        },
    ]


def fake_home_context():
    return {
        "numbers": _numbers(),
        "activity": _activity(),
        "sets": _sets(),
    }
