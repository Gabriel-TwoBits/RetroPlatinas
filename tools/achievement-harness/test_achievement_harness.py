"""Smoke test: boots the disc and reaches the island map with the repo's achievements active.

Skipped (not failed) when CRASH1_CUE is unset or names no file, so the suite stays green without
the disc. The first run downloads the core and builds the shim into the cache.
"""

import achievements
import navigation
import provision
import pytest
from harness import TRIGGERED, Emu
from probes import ISLAND_CAM_STATE, LEVEL_ID, LID_TITLE, ON_THE_MAP


def test_cold_boot_reaches_the_map_without_unlocking_anything():
    try:
        provision.disc()
    except provision.MissingInput as missing:
        pytest.skip(str(missing))
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
