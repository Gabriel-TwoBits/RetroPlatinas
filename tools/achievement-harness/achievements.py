"""The repo's achievements, leaderboards and rich presence, built by the seed commands' own code
(never copied).

Importing a seed command needs Django, so this module puts the repo root on `sys.path` and calls
`django.setup()` with the project's settings before the import.

    python tools/achievement-harness/achievements.py  # achievements, leaderboards, the script
"""

import os
import sys
from dataclasses import dataclass

import django
from django.apps import apps as app_registry
from provision import REPO_ROOT

SETTINGS_ENV = "DJANGO_SETTINGS_MODULE"
DEFAULT_SETTINGS = "retroplatinas.settings.dev"
FIRST_RUNTIME_ID = 1


@dataclass(frozen=True)
class Definition:
    runtime_id: int
    title: str
    mem_addr: str


@dataclass(frozen=True)
class LeaderboardDefinition:
    runtime_id: int
    title: str
    mem_addr: str
    level_id: int  # the stage it times (c1 level id, `0xH6188d`)
    opening: str  # how the stage hands Crash to the player (the seed's INTRO or SPIN_IN)


def _setup_django():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    os.environ.setdefault(SETTINGS_ENV, DEFAULT_SETTINGS)
    if not app_registry.ready:
        django.setup()


def _level_seed():
    _setup_django()
    from apps.achievements.management.commands import seed_crash1_level_achievements

    return seed_crash1_level_achievements


def collectible_seed():
    """`seed_crash1_collectible_achievements`, whose title constants the scenarios expect."""
    _setup_django()
    from apps.achievements.management.commands import seed_crash1_collectible_achievements

    return seed_crash1_collectible_achievements


def advanced_seed():
    """`seed_crash1_advanced_achievements`, whose titles and gem stages the scenarios expect."""
    _setup_django()
    from apps.achievements.management.commands import seed_crash1_advanced_achievements

    return seed_crash1_advanced_achievements


def leaderboard_seed():
    """`seed_crash1_leaderboards`, whose definitions the harness activates."""
    _setup_django()
    from apps.achievements.management.commands import seed_crash1_leaderboards

    return seed_crash1_leaderboards


def rich_presence():
    """The Crash Bandicoot rich presence script, as `seed_crash1_rich_presence` stores it."""
    _setup_django()
    from apps.achievements.management.commands import seed_crash1_rich_presence

    return seed_crash1_rich_presence.build_rich_presence()


def level_title(level_id):
    """Title of the level-completion achievement for a stage (c1 level id, `0xH6188d`)."""
    for title, seeded_level_id in _level_seed().LEVEL_ACHIEVEMENTS:
        if seeded_level_id == level_id:
            return title
    raise KeyError(f"no level achievement is seeded for level {level_id:#x}")


def definitions():
    """Every seeded achievement, numbered from FIRST_RUNTIME_ID: the level achievements, the
    collectible ones, then the advanced ones, each in seed order."""
    level_seed = _level_seed()
    seeded = [
        (title, level_seed.build_mem_addr(level_id))
        for title, level_id in level_seed.LEVEL_ACHIEVEMENTS
    ]
    seeded += [
        (title, mem_addr)
        for title, _description, mem_addr, *_ in collectible_seed().collectible_achievements()
    ]
    seeded += [
        (title, mem_addr)
        for title, _description, mem_addr, *_ in advanced_seed().advanced_achievements()
    ]
    return [
        Definition(FIRST_RUNTIME_ID + index, title, mem_addr)
        for index, (title, mem_addr) in enumerate(seeded)
    ]


def leaderboard_definitions():
    """Every seeded leaderboard, numbered from FIRST_RUNTIME_ID in seed order (rcheevos keeps
    leaderboard ids apart from achievement ids)."""
    return [
        LeaderboardDefinition(FIRST_RUNTIME_ID + index, title, mem_addr, level_id, opening)
        for index, (title, _description, mem_addr, level_id, opening) in enumerate(
            leaderboard_seed().leaderboards()
        )
    ]


if __name__ == "__main__":
    for definition in definitions():
        print(definition.runtime_id, definition.title, definition.mem_addr, sep="\t")
    for leaderboard in leaderboard_definitions():
        print(f"lb{leaderboard.runtime_id}", leaderboard.title, leaderboard.mem_addr, sep="\t")
    print(rich_presence(), end="")
