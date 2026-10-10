"""Headless PS1 emulator driven frame by frame, with the repo's rcheevos runtime judging triggers.

    from harness import Btn, Emu
    emu = Emu().load()                 # pcsx_rearmed interpreter, disc from CRASH1_CUE
    emu.step(600)                      # 600 frames, no input
    emu.step(6, [Btn.START])           # hold START for 6 frames
    emu.u8(0x61994)                    # RA address -> byte of main RAM

Run this module to print the core and rcheevos versions in use.
One emulator per process: libretro cores keep global state, and so does the rcheevos shim.
"""

import ctypes
import tempfile
from pathlib import Path

import provision
from png import BYTES_PER_PIXEL, write_png

BYTES_PER_MIB = 1024 * 1024
PS1_RAM_BYTES = 2 * BYTES_PER_MIB
MAX_FRAME_WIDTH = 1024
MAX_FRAME_HEIGHT = 1024
MAX_FRAMEBUFFER_BYTES = MAX_FRAME_WIDTH * MAX_FRAME_HEIGHT * BYTES_PER_PIXEL
HITS_BUFFER_BYTES = 8192
RICH_PRESENCE_BUFFER_BYTES = 1024
OPTIONS_BUFFER_BYTES = 65536
EVENT_BATCH = 4096
POINTER_BYTES = 3
WORD_BYTES = 4
SHORT_HASH_CHARS = 12
FRAMES_PER_SECOND = 60  # NTSC
SECONDS_PER_MINUTE = 60
DEFAULT_CORE = "pcsx_rearmed"
SWANSTATION = "swanstation"
SWANSTATION_BIOS_OPTION = "swanstation_BIOS_PathNTSCU"

# pcsx_rearmed's lightrec dynarec is not bit-exact across state loads, so the interpreter is the
# default: input plans only replay on a deterministic core. swanstation always needs a real BIOS.
CORE_DEFAULTS = {
    DEFAULT_CORE: {"pcsx_rearmed_drc": "disabled"},
    SWANSTATION: {"swanstation_GPU_Renderer": "Software"},
}

LOAD_ERRORS = {
    -1: "dlopen of the core failed",
    -2: "the core misses a libretro symbol",
    -3: "the disc image cannot be opened",
    -4: "the disc image was read short",
    -5: "the core rejected the disc",
}


class Btn:
    """libretro RETRO_DEVICE_ID_JOYPAD_* bit positions, named after the PS1 pad."""

    CROSS = 0  # libretro B
    SQUARE = 1  # libretro Y
    SELECT = 2
    START = 3
    UP = 4
    DOWN = 5
    LEFT = 6
    RIGHT = 7
    CIRCLE = 8  # libretro A
    TRIANGLE = 9  # libretro X
    L1 = 10
    R1 = 11
    L2 = 12
    R2 = 13


# rc_runtime_event_t types (rc_runtime.h)
EVENT_NAMES = {
    0: "ACHIEVEMENT_ACTIVATED",
    1: "ACHIEVEMENT_PAUSED",
    2: "ACHIEVEMENT_RESET",
    3: "ACHIEVEMENT_TRIGGERED",
    4: "ACHIEVEMENT_PRIMED",
    5: "LBOARD_STARTED",
    6: "LBOARD_CANCELED",
    7: "LBOARD_UPDATED",
    8: "LBOARD_TRIGGERED",
    9: "ACHIEVEMENT_DISABLED",
    10: "LBOARD_DISABLED",
    11: "ACHIEVEMENT_UNPRIMED",
    12: "ACHIEVEMENT_PROGRESS_UPDATED",
}

# rc_trigger_t.state (rc_runtime_types.h); -1 is the shim's "no such achievement".
TRIGGER_STATES = {
    -1: "missing",
    0: "inactive",
    1: "waiting",
    2: "active",
    3: "paused",
    4: "reset",
    5: "triggered",
    6: "primed",
    7: "disabled",
}
TRIGGERED = "triggered"

# rc_condition_t.type (rc_runtime_types.h)
CONDITION_TYPES = {
    0: "Standard",
    1: "PauseIf",
    2: "ResetIf",
    3: "MeasuredIf",
    4: "Trigger",
    5: "Measured",
    6: "AddSource",
    7: "SubSource",
    8: "AddAddress",
    9: "Remember",
    10: "AddHits",
    11: "SubHits",
    12: "ResetNextIf",
    13: "AndNext",
    14: "OrNext",
}

_emulator_created = False


def mask_of(buttons):
    mask = 0
    for button in buttons:
        mask |= 1 << button
    return mask


class Emu:
    def __init__(self, core=DEFAULT_CORE, verbose=False):
        global _emulator_created
        if core not in CORE_DEFAULTS:
            raise ValueError(f"unsupported core {core!r}; choose one of {sorted(CORE_DEFAULTS)}")
        if _emulator_created:
            raise RuntimeError("one emulator per process: the core and the shim are process-global")
        _emulator_created = True
        self.core_name = core
        self.lib = ctypes.CDLL(str(provision.library()))
        self._declare()
        self.lib.h_set_verbose(int(verbose))
        system_dir = provision.SYSTEM_DIR / core
        system_dir.mkdir(parents=True, exist_ok=True)
        # A fresh save dir per process keeps memory cards blank, so every boot is identical.
        self._save_dir = tempfile.TemporaryDirectory(prefix="achievement-harness-")
        self.lib.h_set_dirs(str(system_dir).encode(), self._save_dir.name.encode())
        self.requested_options = dict(CORE_DEFAULTS[core])
        if core == SWANSTATION:
            self.requested_options[SWANSTATION_BIOS_OPTION] = provision.bios_image(system_dir)
        else:
            pass  # pcsx_rearmed boots with its high-level BIOS emulation.
        for key, value in self.requested_options.items():
            self.lib.h_set_option(key.encode(), value.encode())
        self.frame_hooks = []
        self.buttons = 0
        self.pristine = True
        self._fb = ctypes.create_string_buffer(MAX_FRAMEBUFFER_BYTES)

    def _declare(self):
        lib = self.lib
        lib.h_load.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        lib.h_set_dirs.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        lib.h_set_option.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        lib.h_dump_options.argtypes = [ctypes.c_char_p, ctypes.c_int]
        lib.h_core_version.restype = ctypes.c_char_p
        lib.h_rcheevos_version.restype = ctypes.c_char_p
        lib.h_ram.restype = ctypes.c_void_p
        lib.h_ram_size.restype = ctypes.c_size_t
        lib.h_fps.restype = ctypes.c_double
        lib.h_frame.restype = ctypes.c_uint64
        lib.h_set_input.argtypes = [ctypes.c_uint32]
        lib.h_run.argtypes = [ctypes.c_int]
        lib.h_ach_activate.argtypes = [ctypes.c_uint32, ctypes.c_char_p]
        lib.h_lb_activate.argtypes = [ctypes.c_uint32, ctypes.c_char_p]
        lib.h_ach_reset_one.argtypes = [ctypes.c_uint32]
        lib.h_ach_state.argtypes = [ctypes.c_uint32]
        lib.h_ach_hits.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_int]
        lib.h_rp_activate.argtypes = [ctypes.c_char_p]
        lib.h_rp_get.argtypes = [ctypes.c_char_p, ctypes.c_int]
        lib.h_events.argtypes = [
            ctypes.POINTER(ctypes.c_uint64),
            ctypes.POINTER(ctypes.c_int32),
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_int32),
            ctypes.c_int,
        ]
        lib.h_framebuffer_rgb.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.h_state_size.restype = ctypes.c_size_t
        lib.h_save_state.argtypes = [ctypes.c_char_p, ctypes.c_size_t]
        lib.h_load_state.argtypes = [ctypes.c_char_p, ctypes.c_size_t]

    def load(self):
        """Boots the disc named by CRASH1_CUE and checks the requested options took effect."""
        disc = provision.disc()
        core_path = provision.core(self.core_name)
        result = self.lib.h_load(str(core_path).encode(), str(disc).encode())
        if result != 0:
            reason = LOAD_ERRORS.get(result, f"unknown error {result}")
            raise RuntimeError(f"loading {disc} on {self.core_name} failed: {reason}")
        undeclared = sorted(set(self.requested_options) - set(self.options()))
        if undeclared:
            raise RuntimeError(f"{self.core_name} does not declare the options {undeclared}")
        size = self.lib.h_ram_size()
        if not self.lib.h_ram() or size < PS1_RAM_BYTES:
            raise RuntimeError(f"{self.core_name} exposes no 2 MiB SYSTEM_RAM (size={size})")
        return self

    def options(self):
        """Every option the core declared, with its effective value."""
        buf = ctypes.create_string_buffer(OPTIONS_BUFFER_BYTES)
        written = self.lib.h_dump_options(buf, OPTIONS_BUFFER_BYTES)
        lines = buf.raw[:written].decode().splitlines()
        return dict(line.split("=", 1) for line in lines if "=" in line)

    @property
    def core_version(self):
        return self.lib.h_core_version().decode()

    @property
    def rcheevos_version(self):
        commit = provision.rcheevos_commit()[:SHORT_HASH_CHARS]
        return f"{self.lib.h_rcheevos_version().decode()} ({commit})"

    @property
    def fps(self):
        return self.lib.h_fps()

    @property
    def frame(self):
        """Frames run since the boot or since the last state load."""
        return self.lib.h_frame()

    def run(self, frames, mask):
        """Runs `frames` frames holding the buttons in `mask`; frame hooks run after each one."""
        self.pristine = False
        self.buttons = mask
        self.lib.h_set_input(mask)
        if not self.frame_hooks:
            self.lib.h_run(frames)
            return
        for _ in range(frames):
            self.lib.h_run(1)
            for hook in self.frame_hooks:
                hook(self)

    def step(self, frames=1, buttons=()):
        """Runs `frames` frames holding `buttons` (an iterable of Btn values)."""
        self.run(frames, mask_of(buttons))

    def read(self, address, size):
        """Reads `size` bytes of main RAM at an RA address (0x000000-0x1FFFFF)."""
        if address < 0 or address + size > PS1_RAM_BYTES:
            raise IndexError(f"{address:#x}+{size} is outside the 2 MiB main RAM")
        # Some cores reallocate RAM on a state load, so the pointer is fetched on every read.
        return ctypes.string_at(self.lib.h_ram() + address, size)

    def u8(self, address):
        return self.read(address, 1)[0]

    def u24(self, address):
        return int.from_bytes(self.read(address, POINTER_BYTES), "little")

    def u32(self, address):
        return int.from_bytes(self.read(address, WORD_BYTES), "little")

    def s32(self, address):
        return int.from_bytes(self.read(address, WORD_BYTES), "little", signed=True)

    def write_u32(self, address, value):
        """Writes a little-endian word of main RAM (to reach a stage, never to fake an event)."""
        if address < 0 or address + WORD_BYTES > PS1_RAM_BYTES:
            raise IndexError(f"{address:#x}+{WORD_BYTES} is outside the 2 MiB main RAM")
        ctypes.memmove(self.lib.h_ram() + address, value.to_bytes(WORD_BYTES, "little"), WORD_BYTES)

    def deref(self, pointer_address, *offsets, size=1):
        """Follows an RA-style chain (24-bit pointer, +offset per hop) and reads the last hop.

        Returns None on a null or out-of-range hop, as rcheevos reads 0 there.
        """
        address = self.u24(pointer_address)
        for offset in offsets[:-1]:
            if address == 0 or address + offset + POINTER_BYTES > PS1_RAM_BYTES:
                return None
            address = self.u24(address + offset)
        last = offsets[-1] if offsets else 0
        if address == 0 or address + last + size > PS1_RAM_BYTES:
            return None
        return int.from_bytes(self.read(address + last, size), "little")

    def screenshot(self, path):
        """PNG of the last rendered frame; a fade or a transition frame is often black."""
        width = ctypes.c_int()
        height = ctypes.c_int()
        pixels = self.lib.h_framebuffer_rgb(
            self._fb, MAX_FRAMEBUFFER_BYTES, ctypes.byref(width), ctypes.byref(height)
        )
        if pixels < 0:
            raise RuntimeError(f"no framebuffer to capture ({pixels})")
        rgb = self._fb.raw[: pixels * BYTES_PER_PIXEL]
        return write_png(path, width.value, height.value, rgb)

    def snapshot(self):
        """In-memory save state (bytes)."""
        size = self.lib.h_state_size()
        buf = ctypes.create_string_buffer(size)
        if self.lib.h_save_state(buf, size) != 0:
            raise RuntimeError("retro_serialize failed")
        return buf.raw

    def restore(self, blob):
        """Loads an in-memory state; every trigger and leaderboard goes back to WAITING, as in
        emulators."""
        if self.lib.h_load_state(blob, len(blob)) != 0:
            raise RuntimeError("retro_unserialize failed")
        self.pristine = False
        self.lib.h_ach_reset()

    def save_state(self, path):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.snapshot())
        return target

    def load_state(self, path):
        self.restore(Path(path).read_bytes())

    def activate(self, achievement_id, mem_addr):
        result = self.lib.h_ach_activate(achievement_id, mem_addr.encode())
        if result != 0:
            raise ValueError(f"rc_runtime_activate_achievement({achievement_id}) -> {result}")

    def activate_leaderboard(self, leaderboard_id, mem_addr):
        """Loads a leaderboard; its LBOARD_* events come out of `events()`."""
        result = self.lib.h_lb_activate(leaderboard_id, mem_addr.encode())
        if result != 0:
            raise ValueError(f"rc_runtime_activate_lboard({leaderboard_id}) -> {result}")

    def reset_achievement(self, achievement_id):
        """One trigger back to WAITING with zeroed hits; the others keep their state."""
        if self.lib.h_ach_reset_one(achievement_id) != 0:
            raise ValueError(f"achievement {achievement_id} is not active")

    def achievement_state(self, achievement_id):
        return TRIGGER_STATES.get(self.lib.h_ach_state(achievement_id), "unknown")

    def achievement_hits(self, achievement_id):
        """Hit counts per condset (core first): [[(type, required, current, is_true), ...], ...]."""
        buf = ctypes.create_string_buffer(HITS_BUFFER_BYTES)
        written = self.lib.h_ach_hits(achievement_id, buf, HITS_BUFFER_BYTES)
        if written < 0:
            return []
        condsets = []
        for group in buf.raw[:written].decode().split("|"):
            conditions = []
            for token in group.split():
                kind, required, current, is_true = (int(part) for part in token.split(":"))
                conditions.append(
                    (CONDITION_TYPES.get(kind, str(kind)), required, current, is_true)
                )
            if conditions:
                condsets.append(conditions)
        return condsets

    def activate_rich_presence(self, script):
        """Loads a rich presence script; rcheevos then updates it on every frame."""
        result = self.lib.h_rp_activate(script.encode())
        if result != 0:
            raise ValueError(f"rc_runtime_activate_richpresence -> {result}")

    def rich_presence(self):
        """The display string the active script gives for the last frame run."""
        buf = ctypes.create_string_buffer(RICH_PRESENCE_BUFFER_BYTES)
        if self.lib.h_rp_get(buf, RICH_PRESENCE_BUFFER_BYTES) < 0:
            raise RuntimeError("rc_runtime_get_richpresence failed")
        return buf.value.decode()

    def events(self):
        """rcheevos events since the last call: [(frame, name, id, value), ...]; the id is an
        achievement's or, for the LBOARD_* events, a leaderboard's."""
        frames = (ctypes.c_uint64 * EVENT_BATCH)()
        types = (ctypes.c_int32 * EVENT_BATCH)()
        ids = (ctypes.c_uint32 * EVENT_BATCH)()
        values = (ctypes.c_int32 * EVENT_BATCH)()
        count = self.lib.h_events(frames, types, ids, values, EVENT_BATCH)
        return [
            (frames[i], EVENT_NAMES.get(types[i], str(types[i])), ids[i], values[i])
            for i in range(count)
        ]


if __name__ == "__main__":
    emu = Emu().load()
    print(f"core      {emu.core_version} ({emu.core_name}, {emu.fps:.3f} fps)")
    print(f"rcheevos  {emu.rcheevos_version} (vendor/rcheevos)")
    print(f"disc      {provision.disc()}")
