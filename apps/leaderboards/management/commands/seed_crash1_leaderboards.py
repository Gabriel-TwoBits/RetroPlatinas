from django.core.management.base import BaseCommand

from apps.games.models import Console, Game
from apps.leaderboards.models import Leaderboard

GAME_TITLE = "Crash Bandicoot"
PS1_RA_ID = 12

STAGE_LOADED = "0xW618cc!=0"
CURRENT_STAGE_ADDRESS = "0xH619c5"
INSIDE_STAGE = "0xH61994=0"
STAGE_UNLOADED = "0xW618cc=0"
RETURNED_TO_MAP = "0xH61994=1_d0xH61994!=1"
RESULTS_SCREEN = "0xH61998=1"
NEVER = "0=1"

LEADERBOARD_FORMAT = "FRAMES"

# (level name, stage id) — stage ids match LEVEL_ACHIEVEMENTS in the achievements seed.
LEADERBOARDS = [
    ("N. Sanity Beach", 0),
    ("Jungle Rollers", 1),
]


def build_leaderboard_mem(stage_id):
    this_stage = f"{CURRENT_STAGE_ADDRESS}={stage_id}"
    # Start as a level condition (not a single-frame map→stage edge, which failed to align on
    # stage 0). Per the RA docs a submitted board only re-arms after STA goes false then true.
    start = f"STA:{STAGE_LOADED}_{this_stage}_{INSIDE_STAGE}"
    # Submit only on the return to the overworld map. The results-screen flag (0x61998) rises on
    # death too, so any 0x61998-based submit fired on death; a death respawns in-stage and never
    # returns to the map, so this cannot. No cancel is needed for the same reason. `d!=1` (not
    # `d=0`) because leaving a stage passes through a transition value (05/06), never a clean 0→1.
    cancel = f"CAN:{NEVER}"
    submit = f"SUB:{RETURNED_TO_MAP}"
    # Count only active gameplay frames: pause on the results screen (0x61998) and once the stage
    # RAM is unloaded (0x618cc null) on the way back to the map, so neither the tally nor the
    # load-out is measured. The achievement notes treat "unloaded" (0x618cc=0) as distinct from
    # "on the map" (0x61994=1): the load-out sits at 0x61994=0 but 0x618cc=0. A respawn keeps the
    # stage loaded, so a death still costs time. A results-screen latch is unusable — 0x61998
    # spikes on death.
    value = f"VAL:P:{RESULTS_SCREEN}_P:{STAGE_UNLOADED}_M:1=1"
    return f"{start}::{cancel}::{submit}::{value}"


class Command(BaseCommand):
    help = "Seed two Crash Bandicoot 1 speedrun leaderboards (idempotent)."

    def handle(self, *args, **options):
        console, _ = Console.objects.get_or_create(
            ra_id=PS1_RA_ID, defaults={"name": "PlayStation", "short_name": "PS1"}
        )
        game, _ = Game.objects.get_or_create(title=GAME_TITLE, defaults={"console": console})

        existing = set(Leaderboard.objects.filter(game=game).values_list("title", flat=True))
        created = Leaderboard.objects.bulk_create(
            [
                Leaderboard(
                    game=game,
                    title=f"{level_name} — Fastest Clear",
                    description=f"Fastest time to clear {level_name}.",
                    mem_addr=build_leaderboard_mem(stage_id),
                    format=LEADERBOARD_FORMAT,
                    lower_is_better=True,
                )
                for level_name, stage_id in LEADERBOARDS
                if f"{level_name} — Fastest Clear" not in existing
            ]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(created)} leaderboards "
                f"({len(LEADERBOARDS)} total, {len(existing)} already present)."
            )
        )
