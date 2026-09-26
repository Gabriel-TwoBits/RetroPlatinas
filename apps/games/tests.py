import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command

from apps.games.models import MD5_HEX_DIGITS, Console, Game, GameHash

CRASH_MD5_UPPERCASE = "35386FD0891E594C9B6D8A4A5BAA0027"


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


@pytest.mark.django_db
def test_game_hash_is_stored_lowercase(console):
    game = Game.objects.create(title="Crash Bandicoot", console=console)
    gh = GameHash.objects.create(game=game, md5=CRASH_MD5_UPPERCASE, label="NTSC-US")
    gh.refresh_from_db()
    assert gh.md5 == CRASH_MD5_UPPERCASE.lower()


@pytest.mark.django_db
def test_game_hash_validation_lowercases_before_the_unique_check(console):
    game = Game.objects.create(title="Crash Bandicoot", console=console)
    GameHash.objects.create(game=game, md5=CRASH_MD5_UPPERCASE.lower(), label="NTSC-US")
    duplicate = GameHash(game=game, md5=CRASH_MD5_UPPERCASE, label="NTSC-US copy")
    with pytest.raises(ValidationError) as excinfo:
        duplicate.full_clean()
    assert "md5" in excinfo.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize("md5", ["g" * MD5_HEX_DIGITS, "a" * (MD5_HEX_DIGITS - 1)])
def test_game_hash_validation_rejects_non_md5(console, md5):
    game = Game.objects.create(title="Crash Bandicoot", console=console)
    with pytest.raises(ValidationError) as excinfo:
        GameHash(game=game, md5=md5, label="NTSC-US").full_clean()
    assert "md5" in excinfo.value.message_dict


@pytest.mark.django_db
def test_admin_hash_in_uppercase_resolves_through_gameid(client, console):
    game = Game.objects.create(title="Crash Bandicoot", console=console)
    admin = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="pw-secret-123"
    )
    client.force_login(admin)
    resp = client.post(
        "/admin/games/gamehash/add/",
        {"game": game.pk, "md5": CRASH_MD5_UPPERCASE, "label": "NTSC-US"},
    )
    assert resp.status_code == 302
    assert GameHash.objects.get().md5 == CRASH_MD5_UPPERCASE.lower()

    resp = client.post("/dorequest.php", {"r": "gameid", "m": CRASH_MD5_UPPERCASE})
    assert resp.json()["GameID"] == game.pk
