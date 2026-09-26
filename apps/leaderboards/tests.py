import importlib
import subprocess
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError

from apps.games.models import Console, Game
from apps.leaderboards.models import Leaderboard

MEM_ADDR_CHECKER = Path(__file__).resolve().parents[2] / "scripts" / "check-mem-addr.sh"


def run_mem_addr_checker(*mem_addrs):
    return subprocess.run(
        ["bash", str(MEM_ADDR_CHECKER), *mem_addrs],
        capture_output=True,
        text=True,
        check=False,
    )


def test_checker_accepts_a_valid_leaderboard():
    result = run_mem_addr_checker("STA:0xH0001=1::CAN:0=1::SUB:0xH0002=1::VAL:M:1=1")
    assert result.returncode == 0, result.stdout + result.stderr


def test_checker_rejects_a_malformed_leaderboard():
    result = run_mem_addr_checker("STA:0xH01=::VAL:M:1=1")
    assert result.returncode == 1, result.stdout + result.stderr


FORMAT_MIGRATION = importlib.import_module(
    "apps.leaderboards.migrations.0002_leaderboard_format_choices"
)


@pytest.fixture
def game(db):
    console = Console.objects.create(ra_id=12, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


def _leaderboard(game, leaderboard_format):
    return Leaderboard(
        game=game,
        title="Fastest",
        mem_addr="STA:1=1::CAN:0=1::SUB:1=1::VAL:M:1=1",
        format=leaderboard_format,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("leaderboard_format", ["FRAMES", "SECS_AS_MINS", "FIXED3", "FLOAT6"])
def test_leaderboard_accepts_rcheevos_formats(game, leaderboard_format):
    _leaderboard(game, leaderboard_format).full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize("leaderboard_format", ["TIME", "frames", "SECONDS", ""])
def test_leaderboard_rejects_formats_outside_the_choices(game, leaderboard_format):
    with pytest.raises(ValidationError) as error:
        _leaderboard(game, leaderboard_format).full_clean()
    assert "format" in error.value.message_dict


@pytest.mark.django_db
def test_leaderboard_format_defaults_to_value(game):
    leaderboard = Leaderboard.objects.create(game=game, title="Score", mem_addr="VAL:M:1=1")
    assert leaderboard.format == Leaderboard.Format.VALUE


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("FRAMES", "FRAMES"),
        ("FLOAT2", "FLOAT2"),
        ("TIME", "FRAMES"),
        ("TIMESECS", "SECS"),
        ("POINTS", "SCORE"),
        ("OTHER", "SCORE"),
        ("SECONDS", "VALUE"),
        ("", "VALUE"),
    ],
)
def test_format_migration_keeps_valid_formats_and_canonicalizes_the_rest(game, stored, expected):
    leaderboard = _leaderboard(game, stored)
    leaderboard.save()

    FORMAT_MIGRATION.canonicalize_formats(django_apps, None)

    leaderboard.refresh_from_db()
    assert leaderboard.format == expected
