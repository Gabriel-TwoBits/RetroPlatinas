"""A traced play session: emulator + the repo's achievements, leaderboards and rich presence +
per-frame CSV + event log + shots.

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
from probes import (
    ALL,
    FIXED_POINT_SHIFT,
    GAME_STATE,
    GAME_STATE_LEVEL_WON,
    GAME_STATE_PLAYING,
    GAME_STATE_STAGE_CLEARED,
    NO_CONTROL_STATE_FLAG,
    NOISY,
    PAUSED,
    PAUSED_ON,
    PBAK_STATE,
    PLAYER_POINTER,
    RESPAWN_COUNT,
    format_value,
    in_a_stage,
    player_state_flags,
)
from provision import SHOTS_DIR, TRACES_DIR

MAX_AUTO_SHOTS = 120
MAX_SHOT_LABEL_CHARS = 80
FRAME_DIGITS = 6
MASK_HEX_DIGITS = 4
RICH_PRESENCE = "rich_presence"
NO_DEMO = achievements.leaderboard_seed().NO_DEMO
NO_RESPAWN = achievements.leaderboard_seed().NO_RESPAWN
INTRO = achievements.leaderboard_seed().INTRO
SPIN_IN = achievements.leaderboard_seed().SPIN_IN
# rcheevos leaderboard events, by the name the event log uses; UPDATED fires on nearly every frame
# of a timed run, so it only feeds the latest value and stays out of the log.
LEADERBOARD_EVENTS = {
    "LBOARD_STARTED": "started",
    "LBOARD_UPDATED": "updated",
    "LBOARD_CANCELED": "canceled",
    "LBOARD_TRIGGERED": "submitted",
}
QUIET_EVENTS = {"LBOARD_UPDATED"}
# The game states a stage is won with: Stage Clear next, or the map after a death past a checkpoint.
WINNING_GAME_STATES = (GAME_STATE_STAGE_CLEARED, GAME_STATE_LEVEL_WON)
# A state load puts every leaderboard back to waiting without an event of its own.
STATE_LOADED = "reset"
SCREENSHOT_ON_CHANGE = {
    "r6188d",
    "r61994",
    "r61998",
    "w618cc",
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


@dataclass(frozen=True)
class LeaderboardEvent:
    kind: str  # LEADERBOARD_EVENTS value, or STATE_LOADED
    title: str
    clock: int  # Session.clock: frames since the session started, across state loads
    value: int  # the value rcheevos reports (0 on a cancel)
    level_id: int
    game_state: int
    played: int  # Session.played on that frame


def player_in_play(emu):
    """The frames a fastest-clear run should count: the player in a stage (not an attract demo),
    the game state playing, the pause menu closed."""
    return (
        in_a_stage(emu)
        and emu.u32(GAME_STATE) == GAME_STATE_PLAYING
        and emu.s32(PBAK_STATE) == NO_DEMO
        and emu.u8(PAUSED) != PAUSED_ON
    )


def player_object(emu):
    """`(pointer, opening)` of the player object in a stage, outside an attract demo and before
    any respawn, `opening` while its state flags carry NO_CONTROL_STATE_FLAG (the state that opens
    the stage); None elsewhere."""
    flags = player_state_flags(emu)
    if (
        flags is None
        or emu.s32(PBAK_STATE) != NO_DEMO
        or emu.s32(RESPAWN_COUNT) >> FIXED_POINT_SHIFT != NO_RESPAWN
    ):
        return None
    return emu.u24(PLAYER_POINTER), bool(flags & NO_CONTROL_STATE_FLAG)


def handovers(previous, current):
    """The stage openings (the leaderboard seed's INTRO, SPIN_IN) that hand Crash to the player
    on a frame, from `(game state playing, player_object)` of the previous frame and of this one.

    An intro hands him over when the game state turns playing; a spin-in when the same player
    object leaves its opening state.
    """
    playing, player = current
    previous_playing, previous_player = previous
    if not playing or player is None:
        return []
    found = []
    if not previous_playing:
        found.append(INTRO)
    else:
        pass  # The game state was already playing.
    if previous_player is not None and previous_player[0] == player[0]:
        if previous_player[1] and not player[1]:
            found.append(SPIN_IN)
        else:
            pass  # Still in, or already out of, the opening state.
    else:
        pass  # A new player object: no previous state of its own.
    return found


class Tracer:
    """Frame hook: one CSV row per frame from named probes, plus a change and event log."""

    def __init__(self, name, probes, quiet, on_change, on_event):
        TRACES_DIR.mkdir(parents=True, exist_ok=True)
        self.probes = probes
        self.names = [probe_name for probe_name, _reader in probes]
        self.quiet = quiet
        self.on_change = on_change
        self.on_event = on_event
        self.csv_file = (TRACES_DIR / f"{name}.csv").open("w", newline="", encoding="utf-8")
        self.writer = csv.writer(self.csv_file)
        self.writer.writerow(["frame", "input", *self.names])
        self.event_log = (TRACES_DIR / f"{name}.events.log").open("w", encoding="utf-8")
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
            if event not in QUIET_EVENTS:
                self.event_log.write(f"{frame}\tRCHEEVOS\t{event} id={runtime_id} value={value}\n")
            else:
                pass  # The latest value still reaches on_event.
            self.on_event(emu, event, runtime_id, value)
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
        self.leaderboards = achievements.leaderboard_definitions()
        self.leaderboard_titles = {lb.runtime_id: lb.title for lb in self.leaderboards}
        for leaderboard in self.leaderboards:
            self.emu.activate_leaderboard(leaderboard.runtime_id, leaderboard.mem_addr)
        self.leaderboard_events = []
        # A monotonic frame count (emu.frame restarts on a state load), the frames of play so
        # far (player_in_play), the frames where a stage's opening handed Crash to the player
        # (handovers) and the frames a stage was won on (the game state leaves playing for a
        # winning one).
        self.clock = 0
        self.played = 0
        self.handovers = []  # (clock, lid, opening)
        self.wins = []  # clock
        self._previous = (False, None)
        self._last_frame = self.emu.frame
        self.emu.activate_rich_presence(achievements.rich_presence())
        self.presence = []  # (frame, display string) on every change
        probes = [*ALL, (RICH_PRESENCE, lambda emu: emu.rich_presence())]
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
        self.tracer = Tracer(self.name, probes, quiet, self._on_change, self._on_event)
        self.emu.frame_hooks.append(self._record_presence)
        self.emu.frame_hooks.append(self._track_play)
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

    def _record_presence(self, emu):
        text = emu.rich_presence()
        if not self.presence or self.presence[-1][1] != text:
            self.presence.append((emu.frame, text))

    def _track_play(self, emu):
        self.clock += 1
        if emu.frame <= self._last_frame:
            # emu.frame restarts on a state load; `played` still holds the frames before it.
            for leaderboard in self.leaderboards:
                self.leaderboard_events.append(
                    LeaderboardEvent(
                        STATE_LOADED,
                        leaderboard.title,
                        self.clock,
                        0,
                        navigation.level_id(emu),
                        emu.u32(GAME_STATE),
                        self.played,
                    )
                )
        else:
            pass  # The emulation ran on.
        self._last_frame = emu.frame
        if player_in_play(emu):
            self.played += 1
        else:
            pass  # Menus, loads, the clear, the pause menu.
        current = (emu.u32(GAME_STATE) == GAME_STATE_PLAYING, player_object(emu))
        if self._previous[0] and in_a_stage(emu) and emu.u32(GAME_STATE) in WINNING_GAME_STATES:
            self.wins.append(self.clock)
        else:
            pass  # No win on this frame.
        for opening in handovers(self._previous, current):
            self.handovers.append((self.clock, navigation.level_id(emu), opening))
        self._previous = current

    def _on_event(self, emu, event, runtime_id, value):
        kind = LEADERBOARD_EVENTS.get(event)
        if kind is None:
            return  # An achievement event: triggers are read off the achievement states.
        title = self.leaderboard_titles[runtime_id]
        level_id = navigation.level_id(emu)
        self.leaderboard_events.append(
            LeaderboardEvent(
                kind, title, self.clock, value, level_id, emu.u32(GAME_STATE), self.played
            )
        )
        if kind != "updated":
            self.note(f"LEADERBOARD {kind} {title!r} value {value} on lid {level_id:#x}")
            self.shot(f"LEADERBOARD-{kind}-lb{runtime_id}")
        else:
            pass  # Nearly every frame of a run: kept for the judge, neither noted nor shot.

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
        """Ends the trace; returns every Trigger, in order. `presence` keeps the display strings."""
        self.note(f"end; triggers={self.triggers}")
        self.tracer.close()
        return self.triggers
