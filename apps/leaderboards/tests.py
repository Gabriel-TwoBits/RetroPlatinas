import subprocess
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.games.models import Game
from apps.leaderboards.management.commands.seed_crash1_leaderboards import (
    GAME_TITLE,
    LEADERBOARDS,
    build_leaderboard_mem,
)
from apps.leaderboards.models import Leaderboard

LEADERBOARD_COUNT = len(LEADERBOARDS)
MEM_ADDR_CHECKER = Path(__file__).resolve().parents[2] / "scripts" / "check-mem-addr.sh"


def run_mem_addr_checker(*mem_addrs):
    return subprocess.run(
        ["bash", str(MEM_ADDR_CHECKER), *mem_addrs],
        capture_output=True,
        text=True,
        check=False,
    )


def test_seed_leaderboard_mem_addr_parses_in_rcheevos():
    result = run_mem_addr_checker(
        *(build_leaderboard_mem(stage_id) for _, stage_id in LEADERBOARDS)
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_mem_addr_checker_rejects_a_malformed_leaderboard():
    result = run_mem_addr_checker("STA:0xH01=::VAL:M:1=1")
    assert result.returncode == 1, result.stdout + result.stderr


@pytest.mark.django_db
def test_seed_creates_two_leaderboards():
    call_command("seed_crash1_leaderboards", verbosity=0)
    game = Game.objects.get(title=GAME_TITLE)
    assert Leaderboard.objects.filter(game=game).count() == LEADERBOARD_COUNT
    for lb in game.leaderboards.all():
        assert lb.format == "FRAMES"
        assert lb.lower_is_better is True


@pytest.mark.django_db
def test_seed_leaderboards_is_idempotent():
    call_command("seed_crash1_leaderboards", verbosity=0)
    call_command("seed_crash1_leaderboards", verbosity=0)
    game = Game.objects.get(title=GAME_TITLE)
    assert Leaderboard.objects.filter(game=game).count() == LEADERBOARD_COUNT
