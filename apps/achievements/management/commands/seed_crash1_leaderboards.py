from django.core.management.base import BaseCommand
from django.db import transaction

from apps.achievements.management.commands.seed_crash1_collectible_achievements import (
    GAME_STATE_PLAYING,
    NO_DEMO,
)
from apps.achievements.management.commands.seed_crash1_level_achievements import (
    GAME_STATE_ADDRESS,
    LEVEL_ACHIEVEMENTS,
    LEVEL_ID_ADDRESS,
    STAGE_CLEAR_LEVEL_ID,
    TITLE_LEVEL_ID,
    build_mem_addr,
    rcheevos_hex,
)
from apps.achievements.management.commands.seed_crash1_rich_presence import (
    DEMO_PLAYBACK_ADDRESS,
    GAME_STATE_GAME_OVER,
    PLAYER_POINTER_ADDRESS,
)
from apps.achievements.management.crash1 import seed_crash1_game, upsert_leaderboards

# c1 `game_state >> 8` from the frame pause -> quit is picked until the title/map level loads.
GAME_STATE_QUIT = 4
# rcheevos `RC_FORMAT_FRAMES`: the value counts 60 Hz frames and shows as a time.
LEADERBOARD_FORMAT = "FRAMES"
LOWER_IS_BETTER = True
# c1 `paused`: 1 while the pause menu is open, which freezes the stage.
PAUSED_ADDRESS = "0xH56400"
PAUSED = 1
# Bit 15 of the player object's state flags (c1 `state_flags`, +0x120), read at bit 7 of byte
# +0x121: set by the opening states of a stage, cleared when Crash leaves them.
PLAYER_NO_CONTROL_FLAG = "0xT121"
NO_CONTROL = 1
# c1 `respawn_count` (24.8, integer byte): +1 per respawn, 0 again whenever the title/map level
# loads. A respawn replays an opening state, so it would otherwise start a run mid-stage.
RESPAWN_COUNT_ADDRESS = "0xH618a1"
NO_RESPAWN = 0

# How a stage hands Crash to the player, measured in the harness. INTRO: a cutscene (game state 0)
# ends with Crash lying on the sand, getting up on the first button. SPIN_IN: Crash spins in with
# the game state already playing and ignores the pad until the spin ends.
INTRO = "intro"
SPIN_IN = "spin-in"
# Stages with a clear the harness plays (a committed clearing plan), by level achievement title.
TIMED_STAGES = (("N. Sanity Beach", INTRO), ("Jungle Rollers", SPIN_IN))


def leaderboard_title(stage):
    return f"{stage} — Fastest Clear"


def build_description(stage):
    return (
        f"Clear {stage} as fast as you can, timed from the moment Crash can move. "
        "Deaths keep the clock running and the pause menu stops it; quitting or a game over "
        "cancels the run."
    )


def build_handover(opening):
    """The frame a stage's opening hands Crash to the player."""
    if opening == INTRO:
        # Crash then waits for a button, so the run starts without one.
        return f"d{GAME_STATE_ADDRESS}!={GAME_STATE_PLAYING}"
    if opening == SPIN_IN:
        # The game state turns playing 83 frames earlier, as the level loads. The pointer must
        # hold since the previous frame so the flag's previous value is the same object's; on the
        # map it is null.
        return "_".join(
            [
                f"{PLAYER_POINTER_ADDRESS}=d{PLAYER_POINTER_ADDRESS}",
                f"I:{PLAYER_POINTER_ADDRESS}_d{PLAYER_NO_CONTROL_FLAG}={NO_CONTROL}",
                f"I:{PLAYER_POINTER_ADDRESS}_{PLAYER_NO_CONTROL_FLAG}!={NO_CONTROL}",
            ]
        )
    raise ValueError(f"unknown stage opening {opening!r}")


def build_start(level_id, opening):
    """The frame the player gains control of the stage, in this stage with the game state
    playing, outside an attract demo and before any respawn."""
    return "_".join(
        [
            f"{LEVEL_ID_ADDRESS}={rcheevos_hex(level_id)}",
            f"{GAME_STATE_ADDRESS}={GAME_STATE_PLAYING}",
            f"{DEMO_PLAYBACK_ADDRESS}={NO_DEMO}",
            f"{RESPAWN_COUNT_ADDRESS}={NO_RESPAWN}",
            build_handover(opening),
        ]
    )


def build_cancel():
    """The frame the run is lost, still in the stage: pause -> quit or a game over (an empty core,
    one alternative per game state).

    Not "the title/map level loads": a Tawna bonus round's save screen is on that level and
    returns to the stage, where a cancel would let the spin-in start a second run mid-stage
    (`respawn_count` is back to 0). A console reset is the emulator's: `rc_client_reset` puts
    every leaderboard back to waiting.
    """
    return f"S{GAME_STATE_ADDRESS}={GAME_STATE_QUIT}S{GAME_STATE_ADDRESS}={GAME_STATE_GAME_OVER}"


def build_value():
    """Counts the frames of play: paused while the game state is not playing (the clear, a quit,
    a game over), on the Stage Clear level (where the state is playing again on the submit
    frame), on the title/map level (a bonus round's save screen) and while the pause menu is
    open. Deaths keep the state playing, so they count."""
    return (
        f"P:{GAME_STATE_ADDRESS}!={GAME_STATE_PLAYING}_"
        f"P:{LEVEL_ID_ADDRESS}={rcheevos_hex(STAGE_CLEAR_LEVEL_ID)}_"
        f"P:{LEVEL_ID_ADDRESS}={rcheevos_hex(TITLE_LEVEL_ID)}_"
        f"P:{PAUSED_ADDRESS}={PAUSED}_"
        "M:1=1"
    )


def build_leaderboard_mem(level_id, opening):
    """STA/CAN/SUB/VAL; the submit is the stage's level achievement: the frame the stage hands
    over to Stage Clear, or to the map on a clear that skips it."""
    return (
        f"STA:{build_start(level_id, opening)}::CAN:{build_cancel()}::"
        f"SUB:{build_mem_addr(level_id)}::VAL:{build_value()}"
    )


def leaderboards():
    """`(title, description, mem_addr, level_id, opening)` of every seeded leaderboard, in map
    order."""
    level_ids = dict(LEVEL_ACHIEVEMENTS)
    return [
        (
            leaderboard_title(stage),
            build_description(stage),
            build_leaderboard_mem(level_ids[stage], opening),
            level_ids[stage],
            opening,
        )
        for stage, opening in TIMED_STAGES
    ]


class Command(BaseCommand):
    help = (
        "Seed the Crash Bandicoot 1 fastest-clear leaderboards (idempotent); existing rows, "
        "matched by title, get the current definition."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        game, _author = seed_crash1_game()
        rows = [
            (title, description, mem_addr, LEADERBOARD_FORMAT, LOWER_IS_BETTER)
            for title, description, mem_addr, _level_id, _opening in leaderboards()
        ]
        created, updated = upsert_leaderboards(game, rows)
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(rows)} leaderboards: {created} created, {updated} updated."
            )
        )
