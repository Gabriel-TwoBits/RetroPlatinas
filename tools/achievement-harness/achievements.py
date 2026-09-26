"""The repo's achievement definitions, built by the seed commands' own code (never copied strings).

Importing a seed command needs Django, so this module puts the repo root on `sys.path` and calls
`django.setup()` with the project's settings before the import.

    python tools/achievement-harness/achievements.py      # id, title, mem_addr as served
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


def level_title(stage_id):
    """Title of the level-completion achievement for a stage (RA stage id, `0xH619c5`)."""
    for title, seeded_stage_id in _level_seed().LEVEL_ACHIEVEMENTS:
        if seeded_stage_id == stage_id:
            return title
    raise KeyError(f"no level achievement is seeded for stage {stage_id}")


def definitions():
    """Every seeded achievement, numbered from FIRST_RUNTIME_ID in seed order."""
    seed = _level_seed()
    return [
        Definition(FIRST_RUNTIME_ID + index, title, seed.build_mem_addr(stage_id))
        for index, (title, stage_id) in enumerate(seed.LEVEL_ACHIEVEMENTS)
    ]


if __name__ == "__main__":
    for definition in definitions():
        print(definition.runtime_id, definition.title, definition.mem_addr, sep="\t")
