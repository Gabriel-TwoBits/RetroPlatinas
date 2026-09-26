"""A traced play session: emulator + the repo's achievements + per-frame CSV + event log + shots.

Writes `.cache/achievement-harness/traces/<name>.csv` (one row per frame, every probe),
`traces/<name>.events.log` (every probe change, every rcheevos event, free-text notes) and
`shots/<name>/<frame>-<what changed>.png`.
"""

import csv
from dataclasses import dataclass

import achievements
import navigation
import states
from harness import DEFAULT_CORE, TRIGGERED, Emu
from probes import ALL, NOISY, format_value
from provision import SHOTS_DIR, TRACES_DIR

MAX_AUTO_SHOTS = 120
MAX_SHOT_LABEL_CHARS = 80
FRAME_DIGITS = 6
MASK_HEX_DIGITS = 4
SCREENSHOT_ON_CHANGE = {
    "r61994",
    "r61998",
    "w618cc",
    "g_lid",
    "g_game_state",
    "g_respawn_count",
    "g_death_count",
    "g_life_count",
    "paused",
}


def hit_counts(emu, runtime_id):
    """`current/required` for every condition with a hit target, e.g. `12/300`."""
    return ",".join(
        f"{current}/{required}"
        for condset in emu.achievement_hits(runtime_id)
        for _kind, required, current, _is_true in condset
        if required
    )


@dataclass(frozen=True)
class Trigger:
    frame: int
    title: str
    level_id: int  # the lid the game shows on the trigger frame


class Tracer:
    """Frame hook: one CSV row per frame from named probes, plus a change and event log."""

    def __init__(self, name, probes, quiet, on_change):
        TRACES_DIR.mkdir(parents=True, exist_ok=True)
        self.probes = probes
        self.names = [probe_name for probe_name, _reader in probes]
        self.quiet = quiet
        self.on_change = on_change
        self.csv_file = (TRACES_DIR / f"{name}.csv").open("w", newline="")
        self.writer = csv.writer(self.csv_file)
        self.writer.writerow(["frame", "input", *self.names])
        self.event_log = (TRACES_DIR / f"{name}.events.log").open("w")
        self.previous = None

    def note(self, text):
        self.event_log.write(f"# {text}\n")

    def __call__(self, emu):
        values = dict(zip(self.names, (reader(emu) for _name, reader in self.probes)))
        row = [
            emu.frame,
            f"{emu.buttons:0{MASK_HEX_DIGITS}x}",
            *(format_value(values[n]) for n in self.names),
        ]
        self.writer.writerow(row)
        if self.previous is not None:
            for probe_name in self.names:
                old, new = self.previous[probe_name], values[probe_name]
                if old != new and probe_name not in self.quiet:
                    self.event_log.write(
                        f"{emu.frame}\t{probe_name}\t{format_value(old)} -> {format_value(new)}\n"
                    )
            self.on_change(emu, self.previous, values)
        for frame, event, runtime_id, value in emu.events():
            self.event_log.write(f"{frame}\tRCHEEVOS\t{event} id={runtime_id} value={value}\n")
        self.previous = values

    def close(self):
        self.csv_file.close()
        self.event_log.close()


class Session:
    def __init__(self, name, state=None, core=DEFAULT_CORE):
        self.name = name if core == DEFAULT_CORE else f"{core}-{name}"
        self.emu = Emu(core=core).load()
        if state:
            states.load(self.emu, state)
        self.definitions = achievements.definitions()
        self.titles = {definition.runtime_id: definition.title for definition in self.definitions}
        probes = list(ALL)
        quiet = set(NOISY)
        for definition in self.definitions:
            runtime_id = definition.runtime_id
            self.emu.activate(runtime_id, definition.mem_addr)
            probes.append((f"ach{runtime_id}_state", self._state_reader(runtime_id)))
            probes.append((f"ach{runtime_id}_hits", self._hits_reader(runtime_id)))
            quiet.add(f"ach{runtime_id}_hits")
        self.shot_dir = SHOTS_DIR / self.name
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        for stale in self.shot_dir.glob("*.png"):
            stale.unlink()
        self.shots_taken = 0
        self.triggers = []
        self.tracer = Tracer(self.name, probes, quiet, self._on_change)
        self.emu.frame_hooks.append(self.tracer)
        self.note(
            f"session {self.name} from {state or 'cold boot'}; core {self.emu.core_version}; "
            f"rcheevos {self.emu.rcheevos_version}"
        )

    @staticmethod
    def _state_reader(runtime_id):
        return lambda emu: emu.achievement_state(runtime_id)

    @staticmethod
    def _hits_reader(runtime_id):
        return lambda emu: hit_counts(emu, runtime_id)

    def _on_change(self, emu, old, new):
        for runtime_id, title in self.titles.items():
            key = f"ach{runtime_id}_state"
            if old[key] != new[key] and new[key] == TRIGGERED:
                level_id = navigation.level_id(emu)
                self.triggers.append(Trigger(emu.frame, title, level_id))
                self.note(f"TRIGGERED {runtime_id} {title} on lid {level_id:#x}")
                self.shot(f"TRIGGERED-ach{runtime_id}")
        changed = sorted(key for key in SCREENSHOT_ON_CHANGE if old[key] != new[key])
        if changed and self.shots_taken < MAX_AUTO_SHOTS:
            self.shot("_".join(f"{key}-{format_value(new[key])}" for key in changed))

    def note(self, text):
        self.tracer.note(f"frame {self.emu.frame}: {text}")
        print(f"[{self.name} {self.emu.frame}] {text}", flush=True)

    def shot(self, label):
        self.shots_taken += 1
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)
        return self.emu.screenshot(
            self.shot_dir / f"{self.emu.frame:0{FRAME_DIGITS}d}-{safe[:MAX_SHOT_LABEL_CHARS]}.png"
        )

    def step(self, frames=1, buttons=()):
        self.emu.step(frames, buttons)

    def press(self, button, release=navigation.RELEASE_FRAMES):
        navigation.press(self.emu, button, release)

    def wait_until(self, predicate, max_frames, what, buttons=()):
        return navigation.wait_until(self.emu, predicate, max_frames, what, buttons)

    def rearm(self, reason):
        """Resets the achievements that fired, so the next attempt can fire them again.

        The others keep their hits, as in a live session, where only their own ResetIf or a
        state load clears them.
        """
        fired = [
            runtime_id
            for runtime_id in self.titles
            if self.emu.achievement_state(runtime_id) == TRIGGERED
        ]
        for runtime_id in fired:
            self.emu.reset_achievement(runtime_id)
        self.note(f"re-armed {[self.titles[runtime_id] for runtime_id in fired]}: {reason}")

    def close(self):
        """Ends the trace; returns every Trigger, in order."""
        self.note(f"end; triggers={self.triggers}")
        self.tracer.close()
        return self.triggers
