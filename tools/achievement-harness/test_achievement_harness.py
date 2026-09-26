"""Harness tests: the real disc with every repo achievement active, judged by the rcheevos runtime.

Skipped (not failed) when CRASH1_CUE is unset or names no file, so the suite stays green without
the disc. The first run downloads the core, builds the shim and derives the states into the cache.
"""

import subprocess
import sys

import achievements
import navigation
import provision
import pytest
import scenarios
from harness import TRIGGERED, Emu
from probes import ISLAND_CAM_STATE, LEVEL_ID, LID_TITLE, ON_THE_MAP

SCENARIOS_SCRIPT = provision.HARNESS_DIR / "scenarios.py"
OUTPUT_TAIL_CHARS = 4000


@pytest.fixture
def disc():
    try:
        return provision.disc()
    except provision.MissingInput as missing:
        pytest.skip(str(missing))


def test_cold_boot_reaches_the_map_without_unlocking_anything(disc):
    emu = Emu().load()
    definitions = achievements.definitions()
    for definition in definitions:
        emu.activate(definition.runtime_id, definition.mem_addr)

    navigation.boot_to_map(emu)

    assert emu.u8(ISLAND_CAM_STATE) == ON_THE_MAP
    assert emu.u8(LEVEL_ID) == LID_TITLE
    unlocked = [
        definition.title
        for definition in definitions
        if emu.achievement_state(definition.runtime_id) == TRIGGERED
    ]
    assert unlocked == []


@pytest.mark.parametrize("name", list(scenarios.SCENARIOS))
def test_scenario_fires_exactly_the_expected_achievements(disc, name):
    """A clear fires its stage's achievement once, on Stage Clear; nothing else fires anything.

    Each scenario runs in its own process: the core and the rcheevos shim are process-global.
    """
    result = subprocess.run(
        [sys.executable, str(SCENARIOS_SCRIPT), name],
        capture_output=True,
        text=True,
        check=False,
    )

    output = (result.stdout + result.stderr)[-OUTPUT_TAIL_CHARS:]
    assert result.returncode == 0, output
    assert f"OK {name}:" in result.stdout, output
