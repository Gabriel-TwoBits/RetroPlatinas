import logging
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.api.auth import user_from_token
from apps.api.handlers import HANDLERS
from apps.games.models import Console, Game, GameHash

User = get_user_model()

STUB_ACTIONS = [k for k in HANDLERS if k not in ("login2", "gameid")]


@pytest.mark.django_db
def test_dorequest_login2_stub_replaced(client):
    User.objects.create_user(username="alice", password="valid-pw-123")
    response = client.post("/dorequest.php", {"r": "login2", "u": "alice", "p": "valid-pw-123"})
    assert response.json()["Success"] is True


@pytest.mark.django_db
def test_dorequest_missing_r(client):
    response = client.post("/dorequest.php", {})
    data = response.json()
    assert response.status_code == 200
    assert data["Success"] is False
    assert "r" in data["Error"]


@pytest.mark.django_db
def test_dorequest_unknown_action(client):
    response = client.post("/dorequest.php", {"r": "banana"})
    data = response.json()
    assert response.status_code == 200
    assert data["Success"] is False
    assert "banana" in data["Error"]


@pytest.mark.django_db
@pytest.mark.parametrize("action", STUB_ACTIONS)
def test_all_handlers_stubbed(client, action):
    response = client.post("/dorequest.php", {"r": action})
    data = response.json()
    assert response.status_code == 200
    assert data["Success"] is False
    assert data["Error"] == "not implemented"


@pytest.mark.django_db
def test_get_method_rejected(client):
    response = client.get("/dorequest.php")
    assert response.status_code == 405


@pytest.mark.django_db
def test_middleware_logs_request_without_credentials(client, caplog):
    with caplog.at_level(logging.INFO, logger="apps.api"):
        client.post("/dorequest.php", {"r": "login2", "u": "alice", "p": "secret", "t": "tok"})

    assert any("r=login2" in record.message for record in caplog.records)
    assert any("u=alice" in record.message for record in caplog.records)
    assert not any("secret" in record.message for record in caplog.records)
    assert not any("tok" in record.message for record in caplog.records)


# --- login2 ---


@pytest.mark.django_db
def test_login2_returns_token_for_valid_credentials(client):
    User.objects.create_user(
        username="alice", password="valid-pw-123", hardcore_points=10, softcore_points=5
    )
    response = client.post("/dorequest.php", {"r": "login2", "u": "alice", "p": "valid-pw-123"})
    data = response.json()
    assert response.status_code == 200
    assert data["Success"] is True
    assert data["User"] == "alice"
    assert len(data["Token"]) == 64
    assert data["Score"] == 10
    assert data["SoftcoreScore"] == 5
    assert data["Messages"] == 0
    assert data["AccountType"] == "Registered"


@pytest.mark.django_db
def test_login2_persists_token_and_expiration(client):
    user = User.objects.create_user(username="alice", password="valid-pw-123")
    client.post("/dorequest.php", {"r": "login2", "u": "alice", "p": "valid-pw-123"})
    user.refresh_from_db()
    assert user.api_token is not None
    assert len(user.api_token) == 64
    delta = user.api_token_expires_at - timezone.now()
    assert timedelta(days=13) < delta < timedelta(days=15)


@pytest.mark.django_db
def test_login2_wrong_password(client):
    User.objects.create_user(username="alice", password="correct-pw-123")
    response = client.post("/dorequest.php", {"r": "login2", "u": "alice", "p": "wrong"})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."
    assert data["Status"] == 401


@pytest.mark.django_db
def test_login2_unknown_user(client):
    response = client.post("/dorequest.php", {"r": "login2", "u": "nobody", "p": "pw"})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."
    assert data["Status"] == 401


@pytest.mark.django_db
def test_login2_missing_username(client):
    response = client.post("/dorequest.php", {"r": "login2", "p": "pw"})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_login2_missing_password(client):
    response = client.post("/dorequest.php", {"r": "login2", "u": "alice"})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


# --- user_from_token ---


@pytest.mark.django_db
def test_user_from_token_returns_user():
    user = User.objects.create_user(username="alice", password="pw")
    user.api_token = "a" * 64
    user.api_token_expires_at = timezone.now() + timedelta(days=14)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    assert user_from_token("a" * 64) == user


@pytest.mark.django_db
def test_user_from_token_returns_none_for_unknown_token():
    assert user_from_token("z" * 64) is None


@pytest.mark.django_db
def test_user_from_token_returns_none_for_expired_token():
    user = User.objects.create_user(username="alice", password="pw")
    user.api_token = "b" * 64
    user.api_token_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    assert user_from_token("b" * 64) is None


@pytest.mark.django_db
def test_user_from_token_returns_none_for_empty_token():
    assert user_from_token("") is None


# --- gameid ---


@pytest.fixture
def game_with_hash(db):
    console = Console.objects.create(ra_id=12, name="PlayStation", short_name="PS1")
    game = Game.objects.create(title="Crash Bandicoot", console=console)
    gh = GameHash.objects.create(game=game, md5="a" * 32, label="NTSC-US")
    return game, gh


@pytest.mark.django_db
def test_gameid_returns_game_id_for_known_hash(client, game_with_hash):
    game, gh = game_with_hash
    response = client.post("/dorequest.php", {"r": "gameid", "m": gh.md5})
    data = response.json()
    assert response.status_code == 200
    assert data["Success"] is True
    assert data["GameID"] == game.pk


@pytest.mark.django_db
def test_gameid_returns_zero_for_unknown_hash(client):
    response = client.post("/dorequest.php", {"r": "gameid", "m": "b" * 32})
    data = response.json()
    assert response.status_code == 200
    assert data["Success"] is True
    assert data["GameID"] == 0


@pytest.mark.django_db
def test_gameid_returns_zero_for_missing_hash(client):
    response = client.post("/dorequest.php", {"r": "gameid"})
    data = response.json()
    assert response.status_code == 200
    assert data["Success"] is True
    assert data["GameID"] == 0


@pytest.mark.django_db
def test_gameid_is_case_insensitive(client, game_with_hash):
    game, gh = game_with_hash
    uppercase_md5 = gh.md5.upper()
    response = client.post("/dorequest.php", {"r": "gameid", "m": uppercase_md5})
    data = response.json()
    assert data["Success"] is True
    assert data["GameID"] == game.pk
