import pytest
from django.core.management import call_command

from apps.games.models import Console, Game, GameHash


@pytest.fixture
def console():
    return Console.objects.create(ra_id=12, name="PlayStation", short_name="PS1")


@pytest.mark.django_db
def test_console_str(console):
    assert str(console) == "PlayStation"


@pytest.mark.django_db
def test_game_and_hash_creation(console):
    game = Game.objects.create(title="Crash Bandicoot", console=console)
    gh = GameHash.objects.create(game=game, md5="a" * 32, label="NTSC-US")

    assert str(game) == "Crash Bandicoot"
    assert str(gh) == f"NTSC-US ({'a' * 32})"
    assert game.hashes.count() == 1


@pytest.mark.django_db
def test_loaddata_consoles():
    call_command("loaddata", "consoles", verbosity=0)
    assert Console.objects.count() >= 10
