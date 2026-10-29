"""play.Recorder: the hand-played run's inputs and its end, without the emulator."""

from types import SimpleNamespace

from play import RECORD_TAIL_FRAMES, Recorder
from probes import (
    GAME_STATE_GAME_OVER,
    GAME_STATE_LEVEL_WON,
    GAME_STATE_PLAYING,
    LID_GAME_WON,
    LID_NEO_CORTEX,
    LID_TITLE,
)

UP, CROSS = 1 << 4, 1 << 0
EMU = SimpleNamespace(core_name="pcsx_rearmed", core_version="PCSX-ReARMed r26 ff81ed1")


def play_out(recorder, mask, level_id, game_state):
    """Frames on one level until the recorder ends the run: the frame that left the start's
    level and RECORD_TAIL_FRAMES more. Returns how many it took, None when it never ended."""
    for frame in range(1, RECORD_TAIL_FRAMES + 3):
        if recorder.frame(mask, level_id, game_state):
            return frame
    return None


def test_a_won_fight_ends_after_the_tail_and_records_every_mask_as_runs():
    recorder = Recorder(LID_NEO_CORTEX)
    recorder.frame(UP, LID_NEO_CORTEX, GAME_STATE_PLAYING)
    recorder.frame(UP, LID_NEO_CORTEX, GAME_STATE_PLAYING)
    recorder.frame(CROSS, LID_NEO_CORTEX, GAME_STATE_LEVEL_WON)

    frames = play_out(recorder, 0, LID_GAME_WON, GAME_STATE_PLAYING)
    plan = recorder.plan("neo-cortex-start", EMU)

    assert frames == RECORD_TAIL_FRAMES + 1
    assert plan.done
    assert plan.inputs == [[2, UP], [1, CROSS], [RECORD_TAIL_FRAMES + 1, 0]]
    assert plan.start == "neo-cortex-start"


def test_a_game_over_ends_the_run_without_a_win():
    recorder = Recorder(LID_NEO_CORTEX)
    recorder.frame(0, LID_NEO_CORTEX, GAME_STATE_PLAYING)

    frames = play_out(recorder, 0, LID_TITLE, GAME_STATE_GAME_OVER)

    assert frames == RECORD_TAIL_FRAMES + 1
    assert not recorder.plan("neo-cortex-start", EMU).done


def test_a_run_inside_the_start_level_never_ends():
    recorder = Recorder(LID_NEO_CORTEX)

    assert play_out(recorder, UP, LID_NEO_CORTEX, GAME_STATE_PLAYING) is None
