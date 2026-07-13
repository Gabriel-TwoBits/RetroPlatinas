from django.core.management.base import BaseCommand

from apps.achievements.management.commands.seed_crash1_level_achievements import build_mem_addr
from apps.games.models import Console, Game
from apps.leaderboards.models import Leaderboard

GAME_TITLE = "Crash Bandicoot"
PS1_RA_ID = 12

STAGE_LOADED = "0xW618cc!=0"
CURRENT_STAGE_ADDRESS = "0xH619c5"
INSIDE_STAGE = "0xH61994=0"
ON_THE_MAP = "0xH61994=1"
JUST_ENTERED_STAGE = "d0xH61994=1"
FRAME_COUNT_VALUE = "M:1=1"

LEADERBOARD_FORMAT = "FRAMES"

# (level name, stage id) — stage ids match LEVEL_ACHIEVEMENTS in the achievements seed.
LEADERBOARDS = [
    ("N. Sanity Beach", 0),
    ("Jungle Rollers", 1),
]


def build_leaderboard_mem(stage_id):
    this_stage = f"{CURRENT_STAGE_ADDRESS}={stage_id}"
    start = f"STA:{STAGE_LOADED}_{this_stage}_{INSIDE_STAGE}_{JUST_ENTERED_STAGE}"
    cancel = f"CAN:{ON_THE_MAP}"
    # Submit the moment the level-completion achievement would trigger — the same in-game
    # validated detector. A bare results-screen edge (0xH61998) also spikes on stage load,
    # which submitted the timer at 0.01s the instant the level began.
    submit = f"SUB:{build_mem_addr(stage_id)}"
    value = f"VAL:{FRAME_COUNT_VALUE}"
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
