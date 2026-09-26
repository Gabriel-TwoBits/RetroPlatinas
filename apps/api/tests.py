import io
import json
import logging
from datetime import timedelta
from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.accounts.models import API_TOKEN_HEX_LENGTH
from apps.achievements.models import Achievement, UserUnlock
from apps.api.auth import is_expired_token, user_from_token
from apps.api.handlers import (
    ACHIEVEMENT_FLAGS_CORE,
    ACHIEVEMENT_FLAGS_UNOFFICIAL,
    API_TOKEN_LIFETIME,
    GAMEINFOLIST_MAX_IDS,
    HANDLERS,
    LBINFO_DEFAULT_COUNT,
    LEADERBOARD_UNKNOWN_DATETIME,
    PRESENCE_TTL_SECONDS,
    _rarity,
)
from apps.games.models import MD5_HEX_DIGITS, Console, Game, GameHash
from apps.images.catalog import (
    VERSION_PARAM,
    avatar_path,
    badge_path,
    game_icon_path,
    versioned_game_icon_path,
)
from apps.images.rendering import BADGE_SIZE_PX
from apps.leaderboards.models import Leaderboard, LeaderboardEntry

User = get_user_model()

IMPLEMENTED_ACTIONS = (
    "login2",
    "gameid",
    "patch",
    "achievementsets",
    "allprogress",
    "awardachievement",
    "startsession",
    "ping",
    "submitlbentry",
    "lbinfo",
    "systemgames",
    "gameinfolist",
    "hashlibrary",
)
STUB_ACTIONS = [k for k in HANDLERS if k not in IMPLEMENTED_ACTIONS]


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


SERVER_ERROR = {
    "Success": False,
    "Error": "Temporary server error. Please try again.",
    "Status": HTTPStatus.SERVICE_UNAVAILABLE,
}


def _crashing_handler(request):
    raise RuntimeError("handler exploded")


@pytest.mark.django_db
def test_handler_exception_answers_retryable_json_and_logs_traceback(client, caplog):
    with (
        patch.dict(HANDLERS, {"awardachievement": _crashing_handler}),
        caplog.at_level(logging.ERROR, logger="apps.api"),
    ):
        response = client.post("/dorequest.php", {"r": "awardachievement"})

    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response["Content-Type"] == "application/json"
    assert response.json() == SERVER_ERROR
    failures = [
        record
        for record in caplog.records
        if record.name == "apps.api" and record.levelno == logging.ERROR
    ]
    assert len(failures) == 1
    assert "r=awardachievement" in failures[0].getMessage()
    assert failures[0].exc_info[0] is RuntimeError


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
    assert len(data["Token"]) == API_TOKEN_HEX_LENGTH
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
    assert len(user.api_token) == API_TOKEN_HEX_LENGTH
    delta = user.api_token_expires_at - timezone.now()
    assert API_TOKEN_LIFETIME - timedelta(minutes=1) < delta <= API_TOKEN_LIFETIME


INVALID_CREDENTIALS = {
    "Success": False,
    "Error": "Credentials invalid.",
    "Status": HTTPStatus.UNAUTHORIZED,
    "Code": "invalid_credentials",
}
GAME_NOT_FOUND = {
    "Success": False,
    "Error": "Unknown game.",
    "Status": HTTPStatus.NOT_FOUND,
    "Code": "not_found",
}
EXPIRED_TOKEN = {
    "Success": False,
    "Error": "The access token has expired. Please log in again.",
    "Status": HTTPStatus.UNAUTHORIZED,
    "Code": "expired_token",
}


@pytest.mark.django_db
def test_login2_wrong_password(client):
    User.objects.create_user(username="alice", password="correct-pw-123")
    response = client.post("/dorequest.php", {"r": "login2", "u": "alice", "p": "wrong"})
    assert response.status_code == HTTPStatus.OK
    assert response.json() == INVALID_CREDENTIALS


@pytest.mark.django_db
def test_login2_unknown_user(client):
    response = client.post("/dorequest.php", {"r": "login2", "u": "nobody", "p": "pw"})
    assert response.json() == INVALID_CREDENTIALS


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


@pytest.mark.django_db
def test_login2_with_token_reauthenticates(client):
    user = User.objects.create_user(
        username="alice", password="pw", hardcore_points=7, softcore_points=3
    )
    user.api_token = "a" * API_TOKEN_HEX_LENGTH
    user.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    user.save(update_fields=["api_token", "api_token_expires_at"])
    response = client.post(
        "/dorequest.php", {"r": "login2", "u": "alice", "t": "a" * API_TOKEN_HEX_LENGTH}
    )
    data = response.json()
    assert data["Success"] is True
    assert data["User"] == "alice"
    assert len(data["Token"]) == API_TOKEN_HEX_LENGTH
    assert data["Score"] == 7
    assert data["SoftcoreScore"] == 3


@pytest.mark.django_db
def test_login2_echoes_existing_valid_token(client):
    # rc_client fires login2 twice on connect; rotating the token would invalidate
    # the second call. A valid token must be echoed, not replaced.
    user = User.objects.create_user(username="alice", password="pw")
    user.api_token = "a" * API_TOKEN_HEX_LENGTH
    user.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    user.save(update_fields=["api_token", "api_token_expires_at"])
    token_response = client.post(
        "/dorequest.php", {"r": "login2", "u": "alice", "t": "a" * API_TOKEN_HEX_LENGTH}
    )
    assert token_response.json()["Token"] == "a" * API_TOKEN_HEX_LENGTH
    password_response = client.post("/dorequest.php", {"r": "login2", "u": "alice", "p": "pw"})
    assert password_response.json()["Token"] == "a" * API_TOKEN_HEX_LENGTH
    user.refresh_from_db()
    assert user.api_token == "a" * API_TOKEN_HEX_LENGTH


@pytest.mark.django_db
def test_login2_with_token_wrong_username(client):
    owner = User.objects.create_user(username="alice", password="pw")
    owner.api_token = "a" * API_TOKEN_HEX_LENGTH
    owner.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    owner.save(update_fields=["api_token", "api_token_expires_at"])
    response = client.post(
        "/dorequest.php", {"r": "login2", "u": "mallory", "t": "a" * API_TOKEN_HEX_LENGTH}
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_login2_with_expired_token_answers_expired_token(client):
    user = User.objects.create_user(username="alice", password="pw")
    user.api_token = "a" * API_TOKEN_HEX_LENGTH
    user.api_token_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    response = client.post(
        "/dorequest.php", {"r": "login2", "u": "alice", "t": "a" * API_TOKEN_HEX_LENGTH}
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json() == EXPIRED_TOKEN


@pytest.mark.django_db
def test_login2_with_expired_token_of_another_user_answers_invalid_credentials(client):
    user = User.objects.create_user(username="alice", password="pw")
    user.api_token = "a" * API_TOKEN_HEX_LENGTH
    user.api_token_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    response = client.post(
        "/dorequest.php", {"r": "login2", "u": "mallory", "t": "a" * API_TOKEN_HEX_LENGTH}
    )
    assert response.json() == INVALID_CREDENTIALS


@pytest.mark.django_db
def test_login2_with_unknown_token_answers_invalid_credentials(client):
    User.objects.create_user(username="alice", password="pw")
    response = client.post(
        "/dorequest.php", {"r": "login2", "u": "alice", "t": "z" * API_TOKEN_HEX_LENGTH}
    )
    assert response.json() == INVALID_CREDENTIALS


# --- user_from_token ---


@pytest.mark.django_db
def test_user_from_token_returns_user():
    user = User.objects.create_user(username="alice", password="pw")
    user.api_token = "a" * API_TOKEN_HEX_LENGTH
    user.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    user.save(update_fields=["api_token", "api_token_expires_at"])
    assert user_from_token("a" * API_TOKEN_HEX_LENGTH) == user


@pytest.mark.django_db
def test_user_from_token_returns_none_for_unknown_token():
    assert user_from_token("z" * API_TOKEN_HEX_LENGTH) is None


@pytest.mark.django_db
def test_user_from_token_returns_none_for_expired_token():
    user = User.objects.create_user(username="alice", password="pw")
    user.api_token = "b" * API_TOKEN_HEX_LENGTH
    user.api_token_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    assert user_from_token("b" * API_TOKEN_HEX_LENGTH) is None


@pytest.mark.django_db
def test_user_from_token_returns_none_for_empty_token():
    assert user_from_token("") is None


@pytest.mark.django_db
def test_user_from_token_returns_none_for_inactive_user():
    user = User.objects.create_user(username="alice", password="pw", is_active=False)
    user.api_token = "c" * API_TOKEN_HEX_LENGTH
    user.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    user.save(update_fields=["api_token", "api_token_expires_at"])
    assert user_from_token(user.api_token) is None


@pytest.mark.django_db
def test_patch_rejects_token_of_deactivated_user(client, authed_user, game_with_hash):
    user, token = authed_user
    game, _ = game_with_hash
    user.is_active = False
    user.save(update_fields=["is_active"])
    response = client.post(
        "/dorequest.php", {"r": "patch", "u": PLAYER_USERNAME, "t": token, "g": game.pk}
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


# --- u + t on every authenticated action ---

AUTHENTICATED_ACTIONS = (
    "patch",
    "achievementsets",
    "allprogress",
    "startsession",
    "awardachievement",
    "ping",
    "submitlbentry",
)


@pytest.mark.django_db
@pytest.mark.parametrize("action", AUTHENTICATED_ACTIONS)
def test_authenticated_action_rejects_token_of_another_user(client, authed_user, action):
    _make_user("mallory", "m" * API_TOKEN_HEX_LENGTH)
    _, token = authed_user
    response = client.post("/dorequest.php", {"r": action, "u": "mallory", "t": token})
    assert response.json() == INVALID_CREDENTIALS


@pytest.mark.django_db
@pytest.mark.parametrize("action", AUTHENTICATED_ACTIONS)
def test_authenticated_action_rejects_missing_username(client, authed_user, action):
    _, token = authed_user
    response = client.post("/dorequest.php", {"r": action, "t": token})
    assert response.json() == INVALID_CREDENTIALS


@pytest.mark.django_db
@pytest.mark.parametrize("action", AUTHENTICATED_ACTIONS)
def test_authenticated_action_answers_expired_token(client, authed_user, action):
    user, token = authed_user
    user.api_token_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["api_token_expires_at"])
    response = client.post("/dorequest.php", {"r": action, "u": PLAYER_USERNAME, "t": token})
    assert response.json() == EXPIRED_TOKEN


@pytest.mark.django_db
def test_is_expired_token_only_for_the_owner_of_an_expired_token():
    user = User.objects.create_user(username="alice", password="pw")
    user.api_token = "a" * API_TOKEN_HEX_LENGTH
    user.api_token_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    assert is_expired_token("alice", "a" * API_TOKEN_HEX_LENGTH) is True
    assert is_expired_token("mallory", "a" * API_TOKEN_HEX_LENGTH) is False
    assert is_expired_token("alice", "z" * API_TOKEN_HEX_LENGTH) is False
    assert is_expired_token("alice", "") is False


@pytest.mark.django_db
def test_is_expired_token_false_for_a_live_token(authed_user):
    _, token = authed_user
    assert is_expired_token(PLAYER_USERNAME, token) is False


@pytest.mark.django_db
def test_is_expired_token_false_for_inactive_user():
    user = User.objects.create_user(username="alice", password="pw", is_active=False)
    user.api_token = "a" * API_TOKEN_HEX_LENGTH
    user.api_token_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    assert is_expired_token("alice", "a" * API_TOKEN_HEX_LENGTH) is False


# --- gameid ---


@pytest.fixture
def game_with_hash(db):
    console = Console.objects.create(ra_id=12, name="PlayStation", short_name="PS1")
    game = Game.objects.create(title="Crash Bandicoot", console=console)
    gh = GameHash.objects.create(game=game, md5="a" * MD5_HEX_DIGITS, label="NTSC-US")
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
    response = client.post("/dorequest.php", {"r": "gameid", "m": "b" * MD5_HEX_DIGITS})
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


# --- patch ---


PLAYER_USERNAME = "player"


@pytest.fixture
def authed_user(db):
    user = User.objects.create_user(username=PLAYER_USERNAME, password="pw")
    token = "t" * API_TOKEN_HEX_LENGTH
    user.api_token = token
    user.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    user.save(update_fields=["api_token", "api_token_expires_at"])
    return user, token


@pytest.fixture
def achievement_author(db):
    return _make_user("author", "a" * API_TOKEN_HEX_LENGTH)


@pytest.fixture
def game_with_achievements(authed_user, achievement_author):
    console = Console.objects.create(ra_id=12, name="PlayStation", short_name="PS1")
    game = Game.objects.create(
        title="Crash Bandicoot", console=console, rich_presence_patch="Display:\nCrash!"
    )
    Achievement.objects.create(
        game=game,
        author=achievement_author,
        title="Draft One",
        description="d",
        points=5,
        mem_addr="0xH0001=1",
        status=Achievement.STATUS_DRAFT,
    )
    Achievement.objects.create(
        game=game,
        author=achievement_author,
        title="Community One",
        description="c",
        points=10,
        mem_addr="0xH0002=1",
        status=Achievement.STATUS_COMMUNITY,
    )
    Achievement.objects.create(
        game=game,
        author=achievement_author,
        title="Verified One",
        description="v",
        points=25,
        mem_addr="0xH0003=1",
        status=Achievement.STATUS_VERIFIED,
    )
    return game


@pytest.mark.django_db
def test_patch_serves_published_achievements_as_core(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    response = client.post(
        "/dorequest.php", {"r": "patch", "u": PLAYER_USERNAME, "t": token, "g": game.pk}
    )
    data = response.json()
    assert data["Success"] is True
    served = {a["Title"]: a["Flags"] for a in data["PatchData"]["Achievements"]}
    assert served == {
        "Community One": ACHIEVEMENT_FLAGS_CORE,
        "Verified One": ACHIEVEMENT_FLAGS_CORE,
    }


@pytest.mark.django_db
def test_patch_empty_game(client, authed_user):
    _, token = authed_user
    console = Console.objects.create(ra_id=7, name="NES", short_name="NES")
    game = Game.objects.create(title="Empty Game", console=console)
    response = client.post(
        "/dorequest.php", {"r": "patch", "u": PLAYER_USERNAME, "t": token, "g": game.pk}
    )
    data = response.json()
    assert data["Success"] is True
    assert data["PatchData"]["Achievements"] == []


@pytest.mark.django_db
def test_patch_unknown_game(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php", {"r": "patch", "u": PLAYER_USERNAME, "t": token, "g": 99999}
    )
    data = response.json()
    assert data == GAME_NOT_FOUND


@pytest.mark.django_db
def test_patch_missing_game_param(client, authed_user):
    _, token = authed_user
    response = client.post("/dorequest.php", {"r": "patch", "u": PLAYER_USERNAME, "t": token})
    data = response.json()
    assert data == GAME_NOT_FOUND


@pytest.mark.django_db
def test_patch_resolves_the_game_by_hash_when_no_game_id_is_sent(
    client, authed_user, game_with_hash
):
    _, token = authed_user
    game, game_hash = game_with_hash
    response = client.post(
        "/dorequest.php",
        {"r": "patch", "u": PLAYER_USERNAME, "t": token, "m": game_hash.md5.upper()},
    )
    data = response.json()
    assert data["Success"] is True
    assert data["PatchData"]["ID"] == game.pk


@pytest.mark.django_db
def test_patch_unknown_hash(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php",
        {"r": "patch", "u": PLAYER_USERNAME, "t": token, "m": "d" * MD5_HEX_DIGITS},
    )
    assert response.json() == GAME_NOT_FOUND


@pytest.mark.django_db
def test_patch_missing_token(client, game_with_achievements):
    game = game_with_achievements
    response = client.post("/dorequest.php", {"r": "patch", "g": game.pk})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_patch_invalid_token(client, game_with_achievements):
    game = game_with_achievements
    response = client.post(
        "/dorequest.php", {"r": "patch", "t": "z" * API_TOKEN_HEX_LENGTH, "g": game.pk}
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_patch_expired_token(client, game_with_achievements):
    game = game_with_achievements
    user = User.objects.create_user(username="expired", password="pw", email="expired@test.com")
    user.api_token = "e" * API_TOKEN_HEX_LENGTH
    user.api_token_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    response = client.post(
        "/dorequest.php", {"r": "patch", "t": "e" * API_TOKEN_HEX_LENGTH, "g": game.pk}
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_patch_response_shape(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    response = client.post(
        "/dorequest.php", {"r": "patch", "u": PLAYER_USERNAME, "t": token, "g": game.pk}
    )
    patch_data = response.json()["PatchData"]
    assert patch_data["ID"] == game.pk
    assert patch_data["Title"] == game.title
    assert patch_data["ConsoleID"] == game.console.ra_id
    assert patch_data["ImageIcon"] == f"/Images/{game.pk:06d}.png"
    assert "RichPresencePatch" in patch_data
    assert "Achievements" in patch_data
    assert patch_data["Leaderboards"] == []


@pytest.mark.django_db
def test_patch_achievement_shape(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    response = client.post(
        "/dorequest.php", {"r": "patch", "u": PLAYER_USERNAME, "t": token, "g": game.pk}
    )
    ach = response.json()["PatchData"]["Achievements"][0]
    required_fields = (
        "ID",
        "MemAddr",
        "Title",
        "Description",
        "Points",
        "Author",
        "Modified",
        "Created",
        "BadgeName",
        "Flags",
    )
    for field in required_fields:
        assert field in ach, f"Missing field: {field}"


@pytest.mark.django_db
def test_patch_badge_name_zero_padded(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    response = client.post(
        "/dorequest.php", {"r": "patch", "u": PLAYER_USERNAME, "t": token, "g": game.pk}
    )
    for ach in response.json()["PatchData"]["Achievements"]:
        badge = ach["BadgeName"]
        assert len(badge) == 5
        assert badge == f"{ach['ID']:05d}"


@pytest.mark.django_db
def test_patch_rich_presence_passthrough(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    response = client.post(
        "/dorequest.php", {"r": "patch", "u": PLAYER_USERNAME, "t": token, "g": game.pk}
    )
    assert response.json()["PatchData"]["RichPresencePatch"] == game.rich_presence_patch


# --- achievementsets ---


@pytest.mark.django_db
def test_achievementsets_by_hash_returns_core_set(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    gh = GameHash.objects.create(game=game, md5="c" * MD5_HEX_DIGITS, label="NTSC-US")
    response = client.post(
        "/dorequest.php", {"r": "achievementsets", "u": PLAYER_USERNAME, "t": token, "m": gh.md5}
    )
    data = response.json()
    assert data["Success"] is True
    assert data["GameId"] == game.pk
    assert data["Title"] == game.title
    assert data["ConsoleId"] == game.console.ra_id
    assert data["RichPresenceGameId"] == game.pk
    assert len(data["Sets"]) == 1
    core = data["Sets"][0]
    assert core["Type"] == "core"
    assert core["GameId"] == game.pk
    assert core["Leaderboards"] == []
    titles = {a["Title"] for a in core["Achievements"]}
    assert titles == {"Community One", "Verified One"}


@pytest.mark.django_db
def test_achievementsets_achievement_shape(client, authed_user, game_with_achievements):
    _, token = authed_user
    GameHash.objects.create(game=game_with_achievements, md5="c" * MD5_HEX_DIGITS, label="NTSC-US")
    response = client.post(
        "/dorequest.php",
        {"r": "achievementsets", "u": PLAYER_USERNAME, "t": token, "m": "c" * MD5_HEX_DIGITS},
    )
    ach = response.json()["Sets"][0]["Achievements"][0]
    required_fields = (
        "ID",
        "MemAddr",
        "Title",
        "Description",
        "Points",
        "Author",
        "Modified",
        "Created",
        "BadgeName",
        "Flags",
    )
    for field in required_fields:
        assert field in ach, f"Missing field: {field}"


@pytest.mark.django_db
def test_achievementsets_case_insensitive_hash(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    GameHash.objects.create(game=game, md5="c" * MD5_HEX_DIGITS, label="NTSC-US")
    response = client.post(
        "/dorequest.php",
        {"r": "achievementsets", "u": PLAYER_USERNAME, "t": token, "m": "C" * MD5_HEX_DIGITS},
    )
    assert response.json()["GameId"] == game.pk


@pytest.mark.django_db
def test_achievementsets_by_game_id(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    response = client.post(
        "/dorequest.php", {"r": "achievementsets", "u": PLAYER_USERNAME, "t": token, "g": game.pk}
    )
    assert response.json()["GameId"] == game.pk


@pytest.mark.django_db
def test_achievementsets_unknown_hash_returns_not_found(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php",
        {"r": "achievementsets", "u": PLAYER_USERNAME, "t": token, "m": "d" * MD5_HEX_DIGITS},
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Code"] == "not_found"
    assert data["Status"] == 404


@pytest.mark.django_db
def test_achievementsets_without_hash_or_game_id_returns_not_found(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php", {"r": "achievementsets", "u": PLAYER_USERNAME, "t": token}
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Code"] == "not_found"


@pytest.mark.django_db
def test_achievementsets_missing_token(client, game_with_achievements):
    response = client.post("/dorequest.php", {"r": "achievementsets", "m": "c" * MD5_HEX_DIGITS})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


# --- publish semantics (patch + achievementsets) ---

SET_ACTIONS = ("patch", "achievementsets")
NOT_SERVED = None
EXTRA_ACHIEVEMENT_POINTS = 5


def _served_achievements(client, action, requester, game):
    data = client.post(
        "/dorequest.php",
        {"r": action, "u": requester.username, "t": requester.api_token, "g": game.pk},
    ).json()
    assert data["Success"] is True
    if action == "patch":
        return data["PatchData"]["Achievements"]
    elif action == "achievementsets":
        return data["Sets"][0]["Achievements"]
    else:
        raise ValueError(f"{action} does not serve an achievement set")


def _create_achievement(game, author, title, status, achievement_type=Achievement.TYPE_NONE):
    return Achievement.objects.create(
        game=game,
        author=author,
        title=title,
        description=title,
        points=EXTRA_ACHIEVEMENT_POINTS,
        mem_addr="0xH0004=1",
        status=status,
        type=achievement_type,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("action", SET_ACTIONS)
@pytest.mark.parametrize(
    ("status", "requested_by_author", "expected_flags"),
    [
        (Achievement.STATUS_DRAFT, True, ACHIEVEMENT_FLAGS_UNOFFICIAL),
        (Achievement.STATUS_DRAFT, False, NOT_SERVED),
        (Achievement.STATUS_COMMUNITY, True, ACHIEVEMENT_FLAGS_CORE),
        (Achievement.STATUS_COMMUNITY, False, ACHIEVEMENT_FLAGS_CORE),
        (Achievement.STATUS_VERIFIED, True, ACHIEVEMENT_FLAGS_CORE),
        (Achievement.STATUS_VERIFIED, False, ACHIEVEMENT_FLAGS_CORE),
    ],
)
def test_set_serves_achievement_by_status_and_requester(
    client,
    authed_user,
    achievement_author,
    game_with_hash,
    action,
    status,
    requested_by_author,
    expected_flags,
):
    player, _ = authed_user
    game, _ = game_with_hash
    achievement = _create_achievement(game, achievement_author, "Under Test", status)
    requester = achievement_author if requested_by_author else player

    served = {a["ID"]: a["Flags"] for a in _served_achievements(client, action, requester, game)}

    assert served.get(achievement.pk, NOT_SERVED) == expected_flags


@pytest.mark.django_db
@pytest.mark.parametrize("action", SET_ACTIONS)
def test_set_serves_own_drafts_but_never_other_users_drafts(
    client, authed_user, game_with_achievements, action
):
    player, _ = authed_user
    _create_achievement(game_with_achievements, player, "Own Draft", Achievement.STATUS_DRAFT)

    served = {
        a["Title"]: a["Flags"]
        for a in _served_achievements(client, action, player, game_with_achievements)
    }

    assert served == {
        "Own Draft": ACHIEVEMENT_FLAGS_UNOFFICIAL,
        "Community One": ACHIEVEMENT_FLAGS_CORE,
        "Verified One": ACHIEVEMENT_FLAGS_CORE,
    }


# --- achievement type (patch + achievementsets) ---


@pytest.mark.django_db
@pytest.mark.parametrize("action", SET_ACTIONS)
@pytest.mark.parametrize(
    ("achievement_type", "expected_wire_type"),
    [
        (Achievement.TYPE_NONE, ""),
        (Achievement.TYPE_PROGRESSION, "progression"),
        (Achievement.TYPE_WIN_CONDITION, "win_condition"),
        (Achievement.TYPE_MISSABLE, "missable"),
    ],
)
def test_set_serializes_achievement_type(
    client,
    authed_user,
    achievement_author,
    game_with_hash,
    action,
    achievement_type,
    expected_wire_type,
):
    player, _ = authed_user
    game, _ = game_with_hash
    achievement = _create_achievement(
        game, achievement_author, "Typed", Achievement.STATUS_COMMUNITY, achievement_type
    )

    served = {a["ID"]: a["Type"] for a in _served_achievements(client, action, player, game)}

    assert served[achievement.pk] == expected_wire_type


# --- rarity (patch + achievementsets) ---


@pytest.mark.django_db
@pytest.mark.parametrize("action", SET_ACTIONS)
def test_set_serves_rarity_over_the_games_players(
    client, authed_user, achievement_author, game_with_hash, action
):
    player, _ = authed_user
    game, _ = game_with_hash
    common = _create_achievement(game, achievement_author, "Common", Achievement.STATUS_COMMUNITY)
    rare = _create_achievement(game, achievement_author, "Rare", Achievement.STATUS_VERIFIED)
    never = _create_achievement(game, achievement_author, "Never", Achievement.STATUS_VERIFIED)
    rival = _make_user("rival", "r" * API_TOKEN_HEX_LENGTH)
    third = _make_user("third", "h" * API_TOKEN_HEX_LENGTH)
    for user, achievement, hardcore in (
        (player, common, False),
        (player, common, True),
        (rival, common, False),
        (third, rare, False),
    ):
        UserUnlock.objects.create(user=user, achievement=achievement, hardcore=hardcore)

    served = {
        a["ID"]: (a["Rarity"], a["RarityHardcore"])
        for a in _served_achievements(client, action, player, game)
    }

    assert served[common.pk] == (66.67, 33.33)
    assert served[rare.pk] == (33.33, 0.0)
    assert served[never.pk] == (0.0, 0.0)


@pytest.mark.django_db
@pytest.mark.parametrize("action", SET_ACTIONS)
def test_set_serves_zero_rarity_when_the_game_has_no_players(
    client, authed_user, game_with_achievements, action
):
    player, _ = authed_user

    served = _served_achievements(client, action, player, game_with_achievements)

    assert [(a["Rarity"], a["RarityHardcore"]) for a in served] == [(0.0, 0.0), (0.0, 0.0)]


@pytest.mark.django_db
@pytest.mark.parametrize("action", SET_ACTIONS)
def test_set_serves_zero_rarity_on_drafts_and_counts_only_published_unlockers(
    client, authed_user, achievement_author, game_with_hash, action
):
    player, _ = authed_user
    game, _ = game_with_hash
    common = _create_achievement(game, achievement_author, "Common", Achievement.STATUS_COMMUNITY)
    demoted = _create_achievement(game, achievement_author, "Demoted", Achievement.STATUS_DRAFT)
    for user, achievement in ((player, common), (player, demoted), (achievement_author, demoted)):
        UserUnlock.objects.create(user=user, achievement=achievement, hardcore=True)

    served = {
        a["ID"]: (a["Rarity"], a["RarityHardcore"])
        for a in _served_achievements(client, action, achievement_author, game)
    }

    assert served[demoted.pk] == (0.0, 0.0)
    assert served[common.pk] == (100.0, 100.0)


@pytest.mark.parametrize(
    ("unlockers", "players", "expected_json"),
    [
        (1, 3, "33.33"),
        (2, 3, "66.67"),
        (3, 3, "100.0"),
        (0, 0, "0.0"),
        (1, 1_000_000, "0.0"),
        (1, 10_000, "0.01"),
    ],
)
def test_rarity_is_a_plain_decimal_percentage(unlockers, players, expected_json):
    assert json.dumps(_rarity(unlockers, players)) == expected_json


# --- allprogress ---


@pytest.mark.django_db
def test_allprogress_returns_empty_response(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php", {"r": "allprogress", "u": PLAYER_USERNAME, "t": token, "c": 12}
    )
    data = response.json()
    assert data["Success"] is True
    assert data["Response"] == {}


@pytest.mark.django_db
def test_allprogress_missing_token(client):
    response = client.post("/dorequest.php", {"r": "allprogress", "c": 12})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


# --- awardachievement ---


@pytest.mark.django_db
def test_awardachievement_softcore_creates_unlock_and_points(
    client, authed_user, game_with_achievements
):
    user, token = authed_user
    achievement = game_with_achievements.achievements.get(title="Community One")
    response = client.post(
        "/dorequest.php",
        {"r": "awardachievement", "u": PLAYER_USERNAME, "t": token, "a": achievement.pk, "h": "0"},
    )
    data = response.json()
    assert data["Success"] is True
    assert data["AchievementID"] == achievement.pk
    assert UserUnlock.objects.filter(user=user, achievement=achievement, hardcore=False).exists()
    user.refresh_from_db()
    assert user.softcore_points == 10
    assert user.hardcore_points == 0
    assert data["SoftcoreScore"] == 10
    assert data["Score"] == 0


@pytest.mark.django_db
def test_awardachievement_is_idempotent(client, authed_user, game_with_achievements):
    user, token = authed_user
    achievement = game_with_achievements.achievements.get(title="Community One")
    payload = {
        "r": "awardachievement",
        "u": PLAYER_USERNAME,
        "t": token,
        "a": achievement.pk,
        "h": "0",
    }
    client.post("/dorequest.php", payload)
    response = client.post("/dorequest.php", payload)
    assert response.json()["Success"] is True
    assert (
        UserUnlock.objects.filter(user=user, achievement=achievement, hardcore=False).count() == 1
    )
    user.refresh_from_db()
    assert user.softcore_points == 10


@pytest.mark.django_db
def test_awardachievement_hardcore_creates_both_unlocks(
    client, authed_user, game_with_achievements
):
    user, token = authed_user
    achievement = game_with_achievements.achievements.get(title="Verified One")
    response = client.post(
        "/dorequest.php",
        {"r": "awardachievement", "u": PLAYER_USERNAME, "t": token, "a": achievement.pk, "h": "1"},
    )
    data = response.json()
    assert data["Success"] is True
    assert UserUnlock.objects.filter(user=user, achievement=achievement, hardcore=True).exists()
    assert UserUnlock.objects.filter(user=user, achievement=achievement, hardcore=False).exists()
    user.refresh_from_db()
    assert user.hardcore_points == 25
    assert user.softcore_points == 25
    assert data["Score"] == 25
    assert data["SoftcoreScore"] == 25


@pytest.mark.django_db
def test_awardachievement_remaining_decrements(client, authed_user, game_with_achievements):
    _, token = authed_user
    achievement = game_with_achievements.achievements.get(title="Community One")
    response = client.post(
        "/dorequest.php",
        {"r": "awardachievement", "u": PLAYER_USERNAME, "t": token, "a": achievement.pk, "h": "0"},
    )
    assert response.json()["AchievementsRemaining"] == 1


ACHIEVEMENT_NOT_FOUND = {
    "Success": False,
    "Error": "Unknown achievement.",
    "Status": HTTPStatus.NOT_FOUND,
    "Code": "not_found",
}
ACHIEVEMENT_UNPUBLISHED = {
    "Success": False,
    "Error": "Unpublished achievements cannot be unlocked.",
    "Status": HTTPStatus.CONFLICT,
    "Code": "invalid_state",
}


def _award(client, token, achievement_id, hardcore):
    return client.post(
        "/dorequest.php",
        {
            "r": "awardachievement",
            "u": PLAYER_USERNAME,
            "t": token,
            "a": achievement_id,
            "h": hardcore,
        },
    ).json()


@pytest.mark.django_db
def test_awardachievement_unknown_achievement(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php",
        {"r": "awardachievement", "u": PLAYER_USERNAME, "t": token, "a": 99999, "h": "0"},
    )
    assert response.json() == ACHIEVEMENT_NOT_FOUND


@pytest.mark.django_db
def test_awardachievement_invalid_achievement_param(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php",
        {"r": "awardachievement", "u": PLAYER_USERNAME, "t": token, "a": "abc", "h": "0"},
    )
    assert response.json() == ACHIEVEMENT_NOT_FOUND


@pytest.mark.django_db
@pytest.mark.parametrize("hardcore", ["0", "1"])
def test_awardachievement_rejects_the_authors_own_draft(
    client, authed_user, game_with_achievements, hardcore
):
    player, token = authed_user
    draft = _create_achievement(
        game_with_achievements, player, "Own Draft", Achievement.STATUS_DRAFT
    )

    assert _award(client, token, draft.pk, hardcore) == ACHIEVEMENT_UNPUBLISHED
    assert not UserUnlock.objects.filter(user=player).exists()
    player.refresh_from_db()
    assert player.softcore_points == 0
    assert player.hardcore_points == 0


@pytest.mark.django_db
def test_awardachievement_answers_another_users_draft_as_unknown(
    client, authed_user, game_with_achievements
):
    player, token = authed_user
    draft = game_with_achievements.achievements.get(title="Draft One")

    assert _award(client, token, draft.pk, "0") == ACHIEVEMENT_NOT_FOUND
    assert not UserUnlock.objects.filter(user=player).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("title", ["Community One", "Verified One"])
def test_awardachievement_awards_every_published_status(
    client, authed_user, game_with_achievements, title
):
    player, token = authed_user
    achievement = game_with_achievements.achievements.get(title=title)

    data = _award(client, token, achievement.pk, "0")

    assert data["Success"] is True
    assert data["SoftcoreScore"] == achievement.points
    assert UserUnlock.objects.filter(user=player, achievement=achievement).exists()


@pytest.mark.django_db
def test_awardachievement_remaining_reaches_zero_on_the_last_published(
    client, authed_user, game_with_achievements
):
    player, token = authed_user
    _create_achievement(game_with_achievements, player, "Own Draft", Achievement.STATUS_DRAFT)
    community = game_with_achievements.achievements.get(title="Community One")
    verified = game_with_achievements.achievements.get(title="Verified One")

    assert _award(client, token, community.pk, "0")["AchievementsRemaining"] == 1
    assert _award(client, token, verified.pk, "0")["AchievementsRemaining"] == 0


@pytest.mark.django_db
def test_awardachievement_remaining_counts_only_the_requested_mode(
    client, authed_user, game_with_achievements
):
    _, token = authed_user
    community = game_with_achievements.achievements.get(title="Community One")
    verified = game_with_achievements.achievements.get(title="Verified One")

    assert _award(client, token, community.pk, "0")["AchievementsRemaining"] == 1
    # The hardcore unlock also unlocks softcore, completing softcore but not hardcore.
    assert _award(client, token, verified.pk, "1")["AchievementsRemaining"] == 1
    assert _award(client, token, verified.pk, "0")["AchievementsRemaining"] == 0


@pytest.mark.django_db
def test_awardachievement_missing_token(client, game_with_achievements):
    achievement = game_with_achievements.achievements.get(title="Community One")
    response = client.post(
        "/dorequest.php", {"r": "awardachievement", "a": achievement.pk, "h": "0"}
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_awardachievement_invalid_token(client, game_with_achievements):
    achievement = game_with_achievements.achievements.get(title="Community One")
    response = client.post(
        "/dorequest.php",
        {"r": "awardachievement", "t": "z" * API_TOKEN_HEX_LENGTH, "a": achievement.pk, "h": "0"},
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


# --- startsession ---


@pytest.mark.django_db
def test_startsession_missing_token(client, game_with_achievements):
    response = client.post("/dorequest.php", {"r": "startsession", "g": game_with_achievements.pk})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_startsession_invalid_token(client, game_with_achievements):
    response = client.post(
        "/dorequest.php",
        {"r": "startsession", "t": "z" * API_TOKEN_HEX_LENGTH, "g": game_with_achievements.pk},
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_startsession_missing_game_param(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php", {"r": "startsession", "u": PLAYER_USERNAME, "t": token}
    )
    data = response.json()
    assert data == GAME_NOT_FOUND


@pytest.mark.django_db
def test_startsession_invalid_game_param(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php", {"r": "startsession", "u": PLAYER_USERNAME, "t": token, "g": "abc"}
    )
    data = response.json()
    assert data == GAME_NOT_FOUND


@pytest.mark.django_db
def test_startsession_unknown_game(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php", {"r": "startsession", "u": PLAYER_USERNAME, "t": token, "g": 99999}
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json() == GAME_NOT_FOUND


@pytest.mark.django_db
def test_startsession_no_unlocks(client, authed_user, game_with_achievements):
    _, token = authed_user
    response = client.post(
        "/dorequest.php",
        {"r": "startsession", "u": PLAYER_USERNAME, "t": token, "g": game_with_achievements.pk},
    )
    data = response.json()
    assert data["Success"] is True
    assert data["Unlocks"] == []
    assert data["HardcoreUnlocks"] == []
    assert isinstance(data["ServerNow"], int)
    assert data["ServerNow"] > 0


@pytest.mark.django_db
def test_startsession_softcore_unlock_only_in_softcore_array(
    client, authed_user, game_with_achievements
):
    _, token = authed_user
    achievement = game_with_achievements.achievements.get(title="Community One")
    client.post(
        "/dorequest.php",
        {"r": "awardachievement", "u": PLAYER_USERNAME, "t": token, "a": achievement.pk, "h": "0"},
    )
    response = client.post(
        "/dorequest.php",
        {"r": "startsession", "u": PLAYER_USERNAME, "t": token, "g": game_with_achievements.pk},
    )
    data = response.json()
    softcore_ids = {u["ID"] for u in data["Unlocks"]}
    hardcore_ids = {u["ID"] for u in data["HardcoreUnlocks"]}
    assert achievement.pk in softcore_ids
    assert achievement.pk not in hardcore_ids


@pytest.mark.django_db
def test_startsession_hardcore_unlock_in_both_arrays(client, authed_user, game_with_achievements):
    _, token = authed_user
    achievement = game_with_achievements.achievements.get(title="Verified One")
    client.post(
        "/dorequest.php",
        {"r": "awardachievement", "u": PLAYER_USERNAME, "t": token, "a": achievement.pk, "h": "1"},
    )
    response = client.post(
        "/dorequest.php",
        {"r": "startsession", "u": PLAYER_USERNAME, "t": token, "g": game_with_achievements.pk},
    )
    data = response.json()
    softcore_ids = {u["ID"] for u in data["Unlocks"]}
    hardcore_ids = {u["ID"] for u in data["HardcoreUnlocks"]}
    assert achievement.pk in softcore_ids
    assert achievement.pk in hardcore_ids


@pytest.mark.django_db
def test_startsession_unlock_entry_shape(client, authed_user, game_with_achievements):
    _, token = authed_user
    achievement = game_with_achievements.achievements.get(title="Community One")
    client.post(
        "/dorequest.php",
        {"r": "awardachievement", "u": PLAYER_USERNAME, "t": token, "a": achievement.pk, "h": "0"},
    )
    response = client.post(
        "/dorequest.php",
        {"r": "startsession", "u": PLAYER_USERNAME, "t": token, "g": game_with_achievements.pk},
    )
    entry = response.json()["Unlocks"][0]
    assert set(entry.keys()) == {"ID", "When"}
    assert isinstance(entry["When"], int)


# --- ping ---


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_ping_missing_token(client, game_with_achievements):
    response = client.post("/dorequest.php", {"r": "ping", "g": game_with_achievements.pk})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_ping_invalid_token(client, game_with_achievements):
    response = client.post(
        "/dorequest.php",
        {"r": "ping", "t": "z" * API_TOKEN_HEX_LENGTH, "g": game_with_achievements.pk},
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_ping_invalid_game_param(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php", {"r": "ping", "u": PLAYER_USERNAME, "t": token, "g": "abc"}
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Unknown game"


@pytest.mark.django_db
def test_ping_stores_rich_presence(client, authed_user, game_with_achievements):
    user, token = authed_user
    game = game_with_achievements
    response = client.post(
        "/dorequest.php",
        {"r": "ping", "u": PLAYER_USERNAME, "t": token, "g": game.pk, "m": "No N. Sanity Beach"},
    )
    assert response.json()["Success"] is True
    assert cache.get(f"presence:{user.id}:{game.pk}") == "No N. Sanity Beach"


@pytest.mark.django_db
def test_ping_uses_five_minute_ttl(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    with patch("apps.api.handlers.cache.set") as mock_set:
        client.post(
            "/dorequest.php",
            {
                "r": "ping",
                "u": PLAYER_USERNAME,
                "t": token,
                "g": game.pk,
                "m": "No N. Sanity Beach",
            },
        )
    assert mock_set.call_count == 1
    args, kwargs = mock_set.call_args
    assert PRESENCE_TTL_SECONDS == 300
    assert 300 in args or kwargs.get("timeout") == 300


# --- leaderboards (patch + submitlbentry) ---

LEADERBOARD_MEM = "STA:0xH0001=1::CAN:0xH0002=1::SUB:0xH0003=1::VAL:M:1=1"


@pytest.fixture
def game_with_leaderboards(authed_user):
    console = Console.objects.create(ra_id=12, name="PlayStation", short_name="PS1")
    game = Game.objects.create(title="Crash Bandicoot", console=console)
    lb = Leaderboard.objects.create(
        game=game,
        title="N. Sanity Beach — Fastest Clear",
        description="Fastest time to clear N. Sanity Beach.",
        mem_addr=LEADERBOARD_MEM,
        format="FRAMES",
        lower_is_better=True,
    )
    return game, lb


def _make_user(username, token):
    user = User.objects.create_user(username=username, password="pw", email=f"{username}@test.com")
    user.api_token = token
    user.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    user.save(update_fields=["api_token", "api_token_expires_at"])
    return user


@pytest.mark.django_db
def test_patch_serializes_leaderboard(client, authed_user, game_with_leaderboards):
    _, token = authed_user
    game, lb = game_with_leaderboards
    response = client.post(
        "/dorequest.php", {"r": "patch", "u": PLAYER_USERNAME, "t": token, "g": game.pk}
    )
    leaderboards = response.json()["PatchData"]["Leaderboards"]
    assert len(leaderboards) == 1
    entry = leaderboards[0]
    assert entry["ID"] == lb.id
    assert entry["Mem"] == LEADERBOARD_MEM
    assert entry["Format"] == "FRAMES"
    assert entry["LowerIsBetter"] is True
    assert entry["Title"] == lb.title
    assert entry["Description"] == lb.description
    assert entry["Hidden"] is False


@pytest.mark.django_db
def test_achievementsets_serializes_leaderboard(client, authed_user, game_with_leaderboards):
    _, token = authed_user
    game, lb = game_with_leaderboards
    GameHash.objects.create(game=game, md5="d" * MD5_HEX_DIGITS, label="NTSC-US")
    response = client.post(
        "/dorequest.php",
        {"r": "achievementsets", "u": PLAYER_USERNAME, "t": token, "m": "d" * MD5_HEX_DIGITS},
    )
    leaderboards = response.json()["Sets"][0]["Leaderboards"]
    assert len(leaderboards) == 1
    assert leaderboards[0]["ID"] == lb.id
    assert leaderboards[0]["Mem"] == LEADERBOARD_MEM


@pytest.mark.django_db
def test_submitlbentry_creates_entry(client, authed_user, game_with_leaderboards):
    user, token = authed_user
    _, lb = game_with_leaderboards
    response = client.post(
        "/dorequest.php",
        {"r": "submitlbentry", "u": PLAYER_USERNAME, "t": token, "i": lb.id, "s": 1234},
    )
    data = response.json()
    assert data["Success"] is True
    assert data["Response"]["Score"] == 1234
    assert data["Response"]["BestScore"] == 1234
    entry = LeaderboardEntry.objects.get(leaderboard=lb, user=user)
    assert entry.score == 1234


@pytest.mark.django_db
def test_submitlbentry_keeps_best_when_worse(client, authed_user, game_with_leaderboards):
    user, token = authed_user
    _, lb = game_with_leaderboards
    # lower_is_better: 500 is better than 900.
    client.post(
        "/dorequest.php",
        {"r": "submitlbentry", "u": PLAYER_USERNAME, "t": token, "i": lb.id, "s": 500},
    )
    response = client.post(
        "/dorequest.php",
        {"r": "submitlbentry", "u": PLAYER_USERNAME, "t": token, "i": lb.id, "s": 900},
    )
    data = response.json()
    assert data["Response"]["Score"] == 900
    assert data["Response"]["BestScore"] == 500
    assert LeaderboardEntry.objects.get(leaderboard=lb, user=user).score == 500
    assert LeaderboardEntry.objects.filter(leaderboard=lb, user=user).count() == 1


@pytest.mark.django_db
def test_submitlbentry_updates_when_better(client, authed_user, game_with_leaderboards):
    user, token = authed_user
    _, lb = game_with_leaderboards
    client.post(
        "/dorequest.php",
        {"r": "submitlbentry", "u": PLAYER_USERNAME, "t": token, "i": lb.id, "s": 900},
    )
    response = client.post(
        "/dorequest.php",
        {"r": "submitlbentry", "u": PLAYER_USERNAME, "t": token, "i": lb.id, "s": 500},
    )
    assert response.json()["Response"]["BestScore"] == 500
    assert LeaderboardEntry.objects.get(leaderboard=lb, user=user).score == 500


@pytest.mark.django_db
def test_submitlbentry_top_entries_and_rank(client, authed_user, game_with_leaderboards):
    _, token = authed_user
    game, lb = game_with_leaderboards
    rival = _make_user("rival", "r" * API_TOKEN_HEX_LENGTH)
    LeaderboardEntry.objects.create(leaderboard=lb, user=rival, score=300)
    response = client.post(
        "/dorequest.php",
        {"r": "submitlbentry", "u": PLAYER_USERNAME, "t": token, "i": lb.id, "s": 800},
    )
    resp = response.json()["Response"]
    # lower_is_better: rival (300) ranks above player (800).
    assert resp["RankInfo"]["Rank"] == 2
    assert resp["RankInfo"]["NumEntries"] == 2
    top = resp["TopEntries"]
    assert [e["Rank"] for e in top] == [1, 2]
    assert top[0]["User"] == "rival"
    assert top[0]["Score"] == 300
    assert top[1]["User"] == "player"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("lower_is_better", "rival_scores", "submitted", "expected_ranks", "expected_rank"),
    [
        (True, [300, 300, 900], 300, [1, 1, 1, 4], 1),
        (True, [100, 500, 500], 700, [1, 2, 2, 4], 4),
        (False, [900, 900, 100], 500, [1, 1, 3, 4], 3),
    ],
)
def test_submitlbentry_top_entries_rank_ties_like_rank_info(
    client,
    authed_user,
    game_with_leaderboards,
    lower_is_better,
    rival_scores,
    submitted,
    expected_ranks,
    expected_rank,
):
    _, token = authed_user
    _, lb = game_with_leaderboards
    lb.lower_is_better = lower_is_better
    lb.save(update_fields=["lower_is_better"])
    for index, rival_score in enumerate(rival_scores):
        rival = _make_user(f"rival{index}", f"{index}" * API_TOKEN_HEX_LENGTH)
        LeaderboardEntry.objects.create(leaderboard=lb, user=rival, score=rival_score)

    resp = client.post(
        "/dorequest.php",
        {"r": "submitlbentry", "u": PLAYER_USERNAME, "t": token, "i": lb.id, "s": submitted},
    ).json()["Response"]

    top = resp["TopEntries"]
    assert [e["Rank"] for e in top] == expected_ranks
    assert resp["RankInfo"]["Rank"] == expected_rank
    player_entry = next(e for e in top if e["User"] == PLAYER_USERNAME)
    assert player_entry["Rank"] == resp["RankInfo"]["Rank"]


@pytest.mark.django_db
def test_submitlbentry_unknown_leaderboard(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php", {"r": "submitlbentry", "u": PLAYER_USERNAME, "t": token, "i": 999, "s": 1}
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Unknown leaderboard"


@pytest.mark.django_db
def test_submitlbentry_invalid_score(client, authed_user, game_with_leaderboards):
    _, token = authed_user
    _, lb = game_with_leaderboards
    response = client.post(
        "/dorequest.php",
        {"r": "submitlbentry", "u": PLAYER_USERNAME, "t": token, "i": lb.id, "s": "abc"},
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Invalid score"


@pytest.mark.django_db
def test_submitlbentry_missing_token(client, game_with_leaderboards):
    _, lb = game_with_leaderboards
    response = client.post("/dorequest.php", {"r": "submitlbentry", "i": lb.id, "s": 1})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


# --- lbinfo ---


def _info(client, action, **params):
    return client.post("/dorequest.php", {"r": action, **params}).json()


def _board_with_scores(leaderboard, scores):
    """One entry per score, submitted in list order, by users named `p0`, `p1`, …"""
    base = timezone.now()
    for index, score in enumerate(scores):
        user = User.objects.create_user(username=f"p{index}", password="pw")
        entry = LeaderboardEntry.objects.create(leaderboard=leaderboard, user=user, score=score)
        LeaderboardEntry.objects.filter(pk=entry.pk).update(
            submitted_at=base + timedelta(seconds=index)
        )


@pytest.mark.django_db
def test_lbinfo_serves_leaderboard_data_without_authentication(client, game_with_leaderboards):
    game, lb = game_with_leaderboards
    _board_with_scores(lb, [300, 100, 300])

    data = _info(client, "lbinfo", i=lb.id)

    assert data["Success"] is True
    board = data["LeaderboardData"]
    assert board == {
        "LBID": lb.id,
        "GameID": game.pk,
        "LowerIsBetter": 1,
        "LBTitle": lb.title,
        "LBDesc": lb.description,
        "LBFormat": "FRAMES",
        "LBMem": LEADERBOARD_MEM,
        "LBAuthor": None,
        "LBCreated": LEADERBOARD_UNKNOWN_DATETIME,
        "LBUpdated": LEADERBOARD_UNKNOWN_DATETIME,
        "TotalEntries": 3,
        "Entries": board["Entries"],
    }
    first = board["Entries"][0]
    submitted = LeaderboardEntry.objects.get(leaderboard=lb, user__username="p1").submitted_at
    assert first == {
        "User": "p1",
        "AvatarUrl": f"http://testserver{avatar_path('p1')}",
        "DateSubmitted": int(submitted.timestamp()),
        "Score": 100,
        "Rank": 1,
        "Index": 1,
    }
    ranked = [(e["User"], e["Rank"], e["Index"]) for e in board["Entries"]]
    assert ranked == [("p1", 1, 1), ("p0", 2, 2), ("p2", 2, 3)]


@pytest.mark.django_db
def test_lbinfo_sends_lower_is_better_as_zero_when_higher_wins(client, game_with_leaderboards):
    _, lb = game_with_leaderboards
    lb.lower_is_better = False
    lb.save(update_fields=["lower_is_better"])
    _board_with_scores(lb, [100, 300])

    board = _info(client, "lbinfo", i=lb.id)["LeaderboardData"]

    assert board["LowerIsBetter"] == 0
    assert [e["User"] for e in board["Entries"]] == ["p1", "p0"]


@pytest.mark.django_db
def test_lbinfo_empty_board(client, game_with_leaderboards):
    _, lb = game_with_leaderboards
    board = _info(client, "lbinfo", i=lb.id)["LeaderboardData"]
    assert board["TotalEntries"] == 0
    assert board["Entries"] == []


@pytest.mark.django_db
def test_lbinfo_defaults_to_the_first_page(client, game_with_leaderboards):
    _, lb = game_with_leaderboards
    _board_with_scores(lb, range(LBINFO_DEFAULT_COUNT + 5))

    board = _info(client, "lbinfo", i=lb.id)["LeaderboardData"]

    assert [e["Index"] for e in board["Entries"]] == list(range(1, LBINFO_DEFAULT_COUNT + 1))


@pytest.mark.django_db
def test_lbinfo_pages_with_offset_and_count(client, game_with_leaderboards):
    _, lb = game_with_leaderboards
    _board_with_scores(lb, [10, 20, 20, 30, 40])

    entries = _info(client, "lbinfo", i=lb.id, o=2, c=2)["LeaderboardData"]["Entries"]

    # The page opens on the second of two tied entries, which keeps the shared rank.
    assert [(e["User"], e["Rank"], e["Index"]) for e in entries] == [("p2", 2, 3), ("p3", 4, 4)]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("username", "expected_indexes"),
    [
        ("p10", [9, 10, 11, 12, 13]),
        ("p1", [1, 2, 3, 4, 5]),
        ("p19", [16, 17, 18, 19, 20]),
    ],
)
def test_lbinfo_centres_the_page_on_the_user(
    client, game_with_leaderboards, username, expected_indexes
):
    _, lb = game_with_leaderboards
    _board_with_scores(lb, range(20))

    entries = _info(client, "lbinfo", i=lb.id, u=username, c=5)["LeaderboardData"]["Entries"]

    assert [e["Index"] for e in entries] == expected_indexes
    assert username in [e["User"] for e in entries]


@pytest.mark.django_db
def test_lbinfo_centres_on_the_user_among_tied_scores(client, game_with_leaderboards):
    _, lb = game_with_leaderboards
    _board_with_scores(lb, [5] * 9)

    entries = _info(client, "lbinfo", i=lb.id, u="p6", c=3)["LeaderboardData"]["Entries"]

    assert [(e["User"], e["Rank"], e["Index"]) for e in entries] == [
        ("p5", 1, 6),
        ("p6", 1, 7),
        ("p7", 1, 8),
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("username", ["nobody", "author"])
def test_lbinfo_user_without_entry_gets_the_offset_page(
    client, game_with_leaderboards, achievement_author, username
):
    _, lb = game_with_leaderboards
    _board_with_scores(lb, range(10))

    entries = _info(client, "lbinfo", i=lb.id, u=username, o=4, c=2)["LeaderboardData"]["Entries"]

    assert [e["Index"] for e in entries] == [5, 6]


@pytest.mark.django_db
def test_lbinfo_caps_the_count(client, game_with_leaderboards):
    _, lb = game_with_leaderboards
    _board_with_scores(lb, range(4))

    with patch("apps.api.handlers.LBINFO_MAX_COUNT", 3):
        entries = _info(client, "lbinfo", i=lb.id, c=100)["LeaderboardData"]["Entries"]

    assert len(entries) == 3


MISSING_PARAMETER = {
    "Success": False,
    "Error": "One or more required parameters is missing.",
    "Status": HTTPStatus.UNPROCESSABLE_ENTITY,
    "Code": "missing_parameter",
}


def _invalid_parameter(name):
    return {
        "Success": False,
        "Error": f"Invalid {name}: expected an unsigned integer.",
        "Status": HTTPStatus.UNPROCESSABLE_ENTITY,
        "Code": "invalid_parameter",
    }


def _not_found(resource):
    return {
        "Success": False,
        "Error": f"Unknown {resource}.",
        "Status": HTTPStatus.NOT_FOUND,
        "Code": "not_found",
    }


@pytest.mark.django_db
def test_lbinfo_missing_leaderboard_id(client):
    assert _info(client, "lbinfo") == MISSING_PARAMETER


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("params", "invalid_name"),
    [
        ({"i": "abc"}, "i"),
        ({"i": "-1"}, "i"),
        ({"i": "1.5"}, "i"),
        ({"i": str(2**32)}, "i"),
        ({"i": "9" * 5000}, "i"),
        ({"i": "1", "c": "x"}, "c"),
        ({"i": "1", "o": "-3"}, "o"),
    ],
)
def test_lbinfo_invalid_parameter(client, game_with_leaderboards, params, invalid_name):
    assert _info(client, "lbinfo", **params) == _invalid_parameter(invalid_name)


@pytest.mark.django_db
def test_lbinfo_unknown_leaderboard(client):
    assert _info(client, "lbinfo", i=999) == _not_found("leaderboard")


# --- systemgames / gameinfolist / hashlibrary ---


def _icon_url(game):
    return f"http://testserver{versioned_game_icon_path(game)}"


@pytest.fixture
def catalogue(game_with_achievements):
    """Crash (3 achievements, 1 draft) plus an empty PS1 game and a game on another console."""
    crash = game_with_achievements
    ps1 = crash.console
    GameHash.objects.create(game=crash, md5="b" * MD5_HEX_DIGITS, label="NTSC-U")
    GameHash.objects.create(game=crash, md5="a" * MD5_HEX_DIGITS, label="PAL")
    Leaderboard.objects.create(game=crash, title="Speed", mem_addr=LEADERBOARD_MEM)
    Leaderboard.objects.create(game=crash, title="Boxes", mem_addr=LEADERBOARD_MEM)
    apeescape = Game.objects.create(title="Ape Escape", console=ps1)
    n64 = Console.objects.create(ra_id=2, name="Nintendo 64", short_name="N64")
    mario = Game.objects.create(title="Super Mario 64", console=n64)
    GameHash.objects.create(game=mario, md5="c" * MD5_HEX_DIGITS, label="US")
    return crash, apeescape, mario


@pytest.mark.django_db
def test_systemgames_lists_the_consoles_games_without_authentication(client, catalogue):
    crash, apeescape, _ = catalogue

    data = _info(client, "systemgames", s=crash.console.ra_id)

    assert data == {
        "Success": True,
        "Response": [
            {
                "ID": apeescape.pk,
                "Title": "Ape Escape",
                "ImageIcon": game_icon_path(apeescape),
                "ImageUrl": _icon_url(apeescape),
                "NumAchievements": 0,
                "NumLeaderboards": 0,
                "Points": 0,
                "SupportedHashes": [],
            },
            {
                "ID": crash.pk,
                "Title": "Crash Bandicoot",
                "ImageIcon": game_icon_path(crash),
                "ImageUrl": _icon_url(crash),
                "NumAchievements": 2,
                "NumLeaderboards": 2,
                "Points": 35,
                "SupportedHashes": ["a" * MD5_HEX_DIGITS, "b" * MD5_HEX_DIGITS],
            },
        ],
    }


@pytest.mark.django_db
def test_systemgames_missing_console(client):
    assert _info(client, "systemgames") == MISSING_PARAMETER


@pytest.mark.django_db
def test_systemgames_invalid_console(client):
    assert _info(client, "systemgames", s="ps1") == _invalid_parameter("s")


@pytest.mark.django_db
def test_systemgames_unknown_console(client, catalogue):
    assert _info(client, "systemgames", s=99) == _not_found("system")


@pytest.mark.django_db
def test_gameinfolist_serves_the_requested_games(client, catalogue):
    crash, _, mario = catalogue

    data = _info(client, "gameinfolist", g=f"{mario.pk},{crash.pk},{crash.pk},999")

    assert data == {
        "Success": True,
        "Response": [
            {
                "ID": game.pk,
                "Title": game.title,
                "ImageIcon": game_icon_path(game),
                "ImageUrl": _icon_url(game),
            }
            for game in sorted([crash, mario], key=lambda game: game.pk)
        ],
    }


@pytest.mark.django_db
def test_gameinfolist_missing_ids(client):
    assert _info(client, "gameinfolist") == MISSING_PARAMETER


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("ids", "error"),
    [
        (",,", "Invalid g: at least one game ID is required."),
        ("1,x", "Invalid g: expected comma-separated unsigned integers."),
        ("1,-2", "Invalid g: expected comma-separated unsigned integers."),
        (str(2**32), "Invalid g: expected comma-separated unsigned integers."),
    ],
)
def test_gameinfolist_invalid_ids(client, ids, error):
    assert _info(client, "gameinfolist", g=ids) == {
        "Success": False,
        "Error": error,
        "Status": HTTPStatus.UNPROCESSABLE_ENTITY,
        "Code": "invalid_parameter",
    }


@pytest.mark.django_db
def test_gameinfolist_ignores_ids_past_the_cap(client, catalogue):
    crash, _, mario = catalogue
    ids = [crash.pk] * GAMEINFOLIST_MAX_IDS + [mario.pk, "x"]
    data = _info(client, "gameinfolist", g=",".join(str(game_id) for game_id in ids))
    assert [game["ID"] for game in data["Response"]] == [crash.pk]


@pytest.mark.django_db
def test_gameinfolist_unknown_games(client):
    assert _info(client, "gameinfolist", g="998,999") == _not_found("games")


@pytest.mark.django_db
def test_hashlibrary_maps_every_hash_without_a_console(client, catalogue):
    crash, _, mario = catalogue
    assert _info(client, "hashlibrary") == {
        "Success": True,
        "MD5List": {
            "a" * MD5_HEX_DIGITS: crash.pk,
            "b" * MD5_HEX_DIGITS: crash.pk,
            "c" * MD5_HEX_DIGITS: mario.pk,
        },
    }


@pytest.mark.django_db
def test_hashlibrary_filters_by_console(client, catalogue):
    _, _, mario = catalogue
    data = _info(client, "hashlibrary", c=mario.console.ra_id)
    assert data == {"Success": True, "MD5List": {"c" * MD5_HEX_DIGITS: mario.pk}}


@pytest.mark.django_db
def test_hashlibrary_known_console_without_hashes_is_an_empty_map(client, catalogue):
    Console.objects.create(ra_id=3, name="SNES", short_name="SNES")
    assert _info(client, "hashlibrary", c=3) == {"Success": True, "MD5List": {}}


@pytest.mark.django_db
def test_hashlibrary_unknown_console(client, catalogue):
    assert _info(client, "hashlibrary", c=99) == _not_found("console")


@pytest.mark.django_db
def test_hashlibrary_invalid_console(client):
    assert _info(client, "hashlibrary", c="snes") == _invalid_parameter("c")


# --- image URLs ---


def _set_request(client, action, token, game):
    return client.post(
        "/dorequest.php", {"r": action, "u": PLAYER_USERNAME, "t": token, "g": game.pk}
    ).json()


def _png_upload(name):
    buffer = io.BytesIO()
    Image.new("RGBA", (BADGE_SIZE_PX, BADGE_SIZE_PX), "red").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _assert_badge_urls(achievement_payloads):
    assert achievement_payloads
    for payload in achievement_payloads:
        achievement = Achievement.objects.get(pk=payload["ID"])
        assert payload["BadgeURL"] == f"http://testserver{badge_path(achievement)}"
        assert payload["BadgeLockedURL"] == (
            f"http://testserver{badge_path(achievement, locked=True)}"
        )
        assert f"?{VERSION_PARAM}=" in payload["BadgeURL"]
        assert f"?{VERSION_PARAM}=" in payload["BadgeLockedURL"]


@pytest.mark.django_db
def test_patch_serves_absolute_versioned_image_urls(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements

    patch_data = _set_request(client, "patch", token, game)["PatchData"]

    _assert_badge_urls(patch_data["Achievements"])
    assert patch_data["ImageIconURL"] == f"http://testserver{versioned_game_icon_path(game)}"


@pytest.mark.django_db
def test_achievementsets_serves_absolute_versioned_image_urls(
    client, authed_user, game_with_achievements
):
    _, token = authed_user
    game = game_with_achievements

    data = _set_request(client, "achievementsets", token, game)

    icon_url = f"http://testserver{versioned_game_icon_path(game)}"
    assert data["ImageIconUrl"] == icon_url
    assert data["Sets"][0]["ImageIconUrl"] == icon_url
    _assert_badge_urls(data["Sets"][0]["Achievements"])


def _badge_urls(data):
    return {a["ID"]: (a["BadgeURL"], a["BadgeLockedURL"]) for a in data["Sets"][0]["Achievements"]}


@pytest.mark.django_db
def test_set_image_urls_change_when_art_is_uploaded(
    client, settings, tmp_path, authed_user, game_with_achievements
):
    settings.MEDIA_ROOT = tmp_path
    _, token = authed_user
    game = game_with_achievements
    before = _set_request(client, "achievementsets", token, game)
    uploaded = game.achievements.get(title="Verified One")
    uploaded.badge = _png_upload("verified.png")
    uploaded.save()
    game.icon = _png_upload("crash.png")
    game.save()

    after = _set_request(client, "achievementsets", token, game)

    assert after["ImageIconUrl"] != before["ImageIconUrl"]
    old_urls = _badge_urls(before)
    for achievement_id, (url, locked_url) in _badge_urls(after).items():
        badge_changed = achievement_id == uploaded.pk
        assert (url != old_urls[achievement_id][0]) is badge_changed
        assert (locked_url != old_urls[achievement_id][1]) is badge_changed


@pytest.mark.django_db
def test_login2_serves_an_absolute_avatar_url(client):
    User.objects.create_user(username="alice", password="valid-pw-123")

    data = _info(client, "login2", u="alice", p="valid-pw-123")

    assert data["AvatarUrl"] == f"http://testserver{avatar_path('alice')}"
