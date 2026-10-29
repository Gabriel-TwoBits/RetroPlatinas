"""Play a derivable state by hand in a browser and record the inputs as a plan.

For a fight the search cannot win (Neo Cortex): a person plays it, and the plan replays it frame
by frame like a searched one, from the same derivable start. The emulator runs here at 60 Hz;
the page at http://localhost:PORT shows each frame and sends the keyboard or a gamepad's buttons.
The run is recorded from the start state; Backspace (or the gamepad's L2) restarts it. Once the
level leaves the start's level and RECORD_TAIL_FRAMES more have run, the plan is written:
`done` when the level was won (game state 3, or the ending level loaded), else not.

    python tools/achievement-harness/play.py STATE --out PLAN [--port PORT]

Run in the container with the port published, e.g. `podman run -p 127.0.0.1:8765:8765 ...`.
"""

import argparse
import http.server
import json
import threading
import time
from pathlib import Path

import plan as plans
import states
from explore import runs_of
from harness import FRAMES_PER_SECOND, Emu
from probes import GAME_STATE, GAME_STATE_LEVEL_WON, LEVEL_ID, LID_GAME_WON

DEFAULT_PORT = 8765
LISTEN_ADDRESS = "0.0.0.0"  # inside the container; publish the port on the host's loopback only
RECORD_TAIL_FRAMES = 2 * FRAMES_PER_SECOND
FRAME_SECONDS = 1 / FRAMES_PER_SECOND
PAGE = Path(__file__).with_name("play.html")


class Recorder:
    """The button mask of every frame since the start state; decides when the run ended."""

    def __init__(self, start_level_id):
        self.start_level_id = start_level_id
        self.masks = []
        self.left_at = None  # frame index the level first left the start's level
        self.won = False

    def frame(self, mask, level_id, game_state):
        """Records one frame's mask and what it led to; returns whether the run is over."""
        self.masks.append(mask)
        if game_state == GAME_STATE_LEVEL_WON or level_id == LID_GAME_WON:
            self.won = True
        else:
            pass  # Not won on this frame.
        if self.left_at is None and level_id != self.start_level_id:
            self.left_at = len(self.masks)
        else:
            pass  # Still in the start's level, or already leaving it.
        return self.left_at is not None and len(self.masks) - self.left_at >= RECORD_TAIL_FRAMES

    def plan(self, start, emu):
        return plans.Plan(
            start=start,
            core=emu.core_name,
            core_version=emu.core_version,
            done=self.won,
            macros=["played-by-hand"],
            inputs=runs_of(self.masks),
        )


class Shared:
    """What the page and the emulator loop exchange, under one lock."""

    def __init__(self):
        self.lock = threading.Lock()
        self.mask = 0
        self.restart = False
        self.frame = b""
        self.size = (0, 0)
        self.status = {"frames": 0, "saved": None}


def handler(shared):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                self._send(PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/frame":
                with shared.lock:
                    body, (width, height) = shared.frame, shared.size
                self._send(body, "application/octet-stream", {"X-Size": f"{width}x{height}"})
            elif self.path == "/status":
                with shared.lock:
                    body = json.dumps(shared.status).encode()
                self._send(body, "application/json")
            else:
                self.send_error(404)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            mask = body.get("mask")
            if self.path != "/input" or not isinstance(mask, int) or mask < 0:
                self.send_error(400)
                return
            with shared.lock:
                shared.mask = mask
                shared.restart = shared.restart or bool(body.get("restart"))
            self._send(b"{}", "application/json")

        def _send(self, body, content_type, headers=None):
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass  # One request per frame: no access log.

    return Handler


def play(emu, start, out, shared):
    """Runs the emulator at 60 Hz on the page's buttons until a run ends; writes its plan."""
    start_state = emu.snapshot()
    recorder = Recorder(emu.u8(LEVEL_ID))
    next_frame = time.monotonic()
    while True:
        with shared.lock:
            mask, restart = shared.mask, shared.restart
            shared.restart = False
        if restart:
            emu.restore(start_state)
            recorder = Recorder(emu.u8(LEVEL_ID))
        else:
            pass  # The run goes on.
        emu.run(1, mask)
        over = recorder.frame(mask, emu.u8(LEVEL_ID), emu.u32(GAME_STATE))
        rgb, width, height = emu.framebuffer()
        with shared.lock:
            shared.frame, shared.size = rgb, (width, height)
            shared.status["frames"] = len(recorder.masks)
        if over:
            target = plans.save(recorder.plan(start, emu), out)
            with shared.lock:
                shared.status["saved"] = {"path": str(target), "done": recorder.won}
            print(f"plan written to {target}; done={recorder.won}", flush=True)
            return recorder.won
        next_frame += FRAME_SECONDS
        time.sleep(max(next_frame - time.monotonic(), 0))


def main():
    parser = argparse.ArgumentParser(description="Play a state by hand and record a plan.")
    parser.add_argument("state", choices=sorted(states.RECIPES))
    parser.add_argument("--out", required=True, help="plan to write")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    emu = Emu().load()
    states.load(emu, args.state)
    shared = Shared()
    server = http.server.ThreadingHTTPServer((LISTEN_ADDRESS, args.port), handler(shared))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"open http://localhost:{args.port} and play; Backspace restarts", flush=True)
    won = play(emu, args.state, args.out, shared)
    server.shutdown()
    return 0 if won else 1


if __name__ == "__main__":
    raise SystemExit(main())
