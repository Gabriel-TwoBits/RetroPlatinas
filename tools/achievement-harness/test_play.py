"""play.Recorder: the hand-played run's inputs and its end, without the emulator."""

import http.server
import sys
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import plan as plans
import play as play_module
import pytest
from play import (
    RECORD_TAIL_FRAMES,
    BitRecorder,
    Recorder,
    Shared,
    handler,
    masks_of,
    parse_bit,
    play,
)
from probes import (
    GAME_STATE,
    GAME_STATE_CUTSCENE,
    GAME_STATE_GAME_OVER,
    GAME_STATE_LEVEL_WON,
    GAME_STATE_PLAYING,
    LEVEL_ID,
    LID_GAME_WON,
    LID_NEO_CORTEX,
    LID_SUNSET_VISTA,
    LID_TITLE,
)

UP, CROSS = 1 << 4, 1 << 0
LID_BONUS_ROUND = 0x34
LID_BONUS_TAWNA = 0x24
LOOPBACK = "127.0.0.1"
HTTP_OK = 200
HTTP_BAD_REQUEST = 400
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


def test_a_key_run_goes_on_through_a_bonus_round_until_the_bit_rises():
    recorder = BitRecorder(LID_SUNSET_VISTA)

    assert not recorder.frame(0, LID_BONUS_ROUND, GAME_STATE_PLAYING)
    for _ in range(RECORD_TAIL_FRAMES):
        assert not recorder.frame(0, LID_BONUS_ROUND, GAME_STATE_PLAYING)
    for _ in range(RECORD_TAIL_FRAMES):
        assert not recorder.frame(0, LID_BONUS_ROUND, GAME_STATE_PLAYING, True)

    assert recorder.frame(0, LID_BONUS_ROUND, GAME_STATE_PLAYING, True)
    assert recorder.plan("sunset-vista-start", EMU).done


def test_a_key_run_goes_on_through_a_save_screen_on_the_title_level():
    recorder = BitRecorder(LID_SUNSET_VISTA)

    assert play_out(recorder, 0, LID_TITLE, GAME_STATE_CUTSCENE) is None


def test_a_game_over_ends_a_key_run_without_a_win():
    recorder = BitRecorder(LID_SUNSET_VISTA)

    frames = play_out(recorder, 0, LID_TITLE, GAME_STATE_GAME_OVER)

    assert frames == RECORD_TAIL_FRAMES + 1
    assert not recorder.plan("sunset-vista-start", EMU).done


def test_a_bit_argument_is_an_address_and_a_bit():
    assert parse_bit("0x619AE:4") == (0x619AE, 4)


class ScriptedEmu:
    """A game that enters the bonus round at BONUS_FRAME and gets the bit at KEY_FRAME; the emulator
    surface `play.play` uses, its one state the frame count."""

    BONUS_FRAME = 3
    KEY_FRAME = 7
    KEY_ADDRESS, KEY_BIT = 0x619AE, 4
    core_name, core_version = EMU.core_name, EMU.core_version

    def __init__(self, shared):
        self.frame = 0
        self.shared = shared
        self.restarted = False

    def snapshot(self):
        return self.frame

    def restore(self, frame):
        self.frame = frame

    def run(self, _frames, _mask):
        self.frame += 1
        if self.frame == self.KEY_FRAME - 1 and not self.restarted:
            self.restarted = True
            self.shared.restart = True
        else:
            pass  # The run goes on.

    def framebuffer(self):
        return b"", 0, 0

    def u8(self, address):
        if address == LEVEL_ID:
            return LID_BONUS_ROUND if self.frame >= self.BONUS_FRAME else LID_SUNSET_VISTA
        if address == self.KEY_ADDRESS:
            return (self.frame >= self.KEY_FRAME and self.restarted) << self.KEY_BIT
        raise ValueError(f"unexpected read of {address:#x}")

    def u32(self, address):
        assert address == GAME_STATE
        return GAME_STATE_PLAYING


def test_a_key_run_restarts_from_the_bonus_round_keeping_the_inputs_before_it(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(play_module, "CHECKPOINTS_DIR", tmp_path)
    monkeypatch.setattr(play_module.time, "sleep", lambda _seconds: None)
    shared = Shared()
    emu = ScriptedEmu(shared)
    out = tmp_path / "key.json"

    won = play(emu, "start", out, shared, (emu.KEY_ADDRESS, emu.KEY_BIT))

    played = plans.load(out)
    restart_point = plans.load(tmp_path / f"key{play_module.RESTART_PLAN_SUFFIX}")
    assert won
    assert restart_point.frames == emu.BONUS_FRAME
    assert not restart_point.done
    assert played.frames == emu.KEY_FRAME + RECORD_TAIL_FRAMES


def test_a_tawna_bonus_round_does_not_move_the_restart_point(tmp_path, monkeypatch):
    monkeypatch.setattr(play_module, "CHECKPOINTS_DIR", tmp_path)
    monkeypatch.setattr(play_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(sys.modules[__name__], "LID_BONUS_ROUND", LID_BONUS_TAWNA)
    shared = Shared()
    emu = ScriptedEmu(shared)

    play(emu, "start", tmp_path / "key.json", shared, (emu.KEY_ADDRESS, emu.KEY_BIT))

    assert not (tmp_path / f"key{play_module.RESTART_PLAN_SUFFIX}").exists()


def test_a_resumed_key_run_keeps_the_saved_inputs_and_restarts_after_them(tmp_path, monkeypatch):
    monkeypatch.setattr(play_module, "CHECKPOINTS_DIR", tmp_path)
    monkeypatch.setattr(play_module.time, "sleep", lambda _seconds: None)
    shared = Shared()
    emu = ScriptedEmu(shared)
    emu.frame = emu.BONUS_FRAME
    out = tmp_path / "key.json"

    play(emu, "start", out, shared, (emu.KEY_ADDRESS, emu.KEY_BIT), [0] * emu.BONUS_FRAME)

    assert plans.load(out).frames == emu.KEY_FRAME + RECORD_TAIL_FRAMES
    assert not (tmp_path / f"key{play_module.RESTART_PLAN_SUFFIX}").exists()


def test_masks_of_expands_input_runs():
    assert masks_of([[2, UP], [1, CROSS]]) == [UP, UP, CROSS]


@pytest.fixture
def server():
    shared = Shared()
    httpd = http.server.ThreadingHTTPServer((LOOPBACK, 0), handler(shared))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield shared, httpd.server_address[1]
    httpd.shutdown()


def post(port, body):
    request = urllib.request.Request(f"http://{LOOPBACK}:{port}/input", data=body, method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b'{"mask": -1}',
        b'{"mask": "1"}',
        b'{"mask": true}',
        b'{"mask": 65536}',
        b"{}",
    ],
)
def test_input_rejects_a_body_that_is_not_a_button_mask(server, body):
    shared, port = server

    assert post(port, body) == HTTP_BAD_REQUEST
    assert shared.mask == 0


def test_input_takes_a_button_mask_and_a_restart(server):
    shared, port = server

    assert post(port, b'{"mask": 17, "restart": true}') == HTTP_OK
    assert (shared.mask, shared.restart) == (UP | CROSS, True)
