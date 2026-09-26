import logging
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.models import API_TOKEN_HEX_LENGTH
from apps.achievements.models import Achievement, UserUnlock
from apps.api.auth import user_from_token
from apps.api.handlers import (
    API_TOKEN_LIFETIME,
    DEFAULT_GAME_ICON_PATH,
    HANDLERS,
    PRESENCE_TTL_SECONDS,
)
from apps.games.models import Console, Game, GameHash
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


@pytest.mark.django_db
def test_login2_with_token_reauthenticates(client):
    user = User.objects.create_user(
        username="alice", password="pw", hardcore_points=7, softcore_points=3
    )
    user.api_token = "a" * 64
    user.api_token_expires_at = timezone.now() + timedelta(days=14)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    response = client.post("/dorequest.php", {"r": "login2", "u": "alice", "t": "a" * 64})
    data = response.json()
    assert data["Success"] is True
    assert data["User"] == "alice"
    assert len(data["Token"]) == 64
    assert data["Score"] == 7
    assert data["SoftcoreScore"] == 3


@pytest.mark.django_db
def test_login2_echoes_existing_valid_token(client):
    # rc_client fires login2 twice on connect; rotating the token would invalidate
    # the second call. A valid token must be echoed, not replaced.
    user = User.objects.create_user(username="alice", password="pw")
    user.api_token = "a" * 64
    user.api_token_expires_at = timezone.now() + timedelta(days=14)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    token_response = client.post("/dorequest.php", {"r": "login2", "u": "alice", "t": "a" * 64})
    assert token_response.json()["Token"] == "a" * 64
    password_response = client.post("/dorequest.php", {"r": "login2", "u": "alice", "p": "pw"})
    assert password_response.json()["Token"] == "a" * 64
    user.refresh_from_db()
    assert user.api_token == "a" * 64


@pytest.mark.django_db
def test_login2_with_token_wrong_username(client):
    owner = User.objects.create_user(username="alice", password="pw")
    owner.api_token = "a" * 64
    owner.api_token_expires_at = timezone.now() + timedelta(days=14)
    owner.save(update_fields=["api_token", "api_token_expires_at"])
    response = client.post("/dorequest.php", {"r": "login2", "u": "mallory", "t": "a" * 64})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_login2_with_expired_token(client):
    user = User.objects.create_user(username="alice", password="pw")
    user.api_token = "a" * 64
    user.api_token_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    response = client.post("/dorequest.php", {"r": "login2", "u": "alice", "t": "a" * 64})
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
    response = client.post("/dorequest.php", {"r": "patch", "t": token, "g": game.pk})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


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


# --- patch ---


@pytest.fixture
def authed_user(db):
    user = User.objects.create_user(username="player", password="pw")
    token = "t" * 64
    user.api_token = token
    user.api_token_expires_at = timezone.now() + timedelta(days=14)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    return user, token


@pytest.fixture
def game_with_achievements(authed_user):
    user, _ = authed_user
    console = Console.objects.create(ra_id=12, name="PlayStation", short_name="PS1")
    game = Game.objects.create(
        title="Crash Bandicoot", console=console, rich_presence_patch="Display:\nCrash!"
    )
    Achievement.objects.create(
        game=game,
        author=user,
        title="Draft One",
        description="d",
        points=5,
        mem_addr="0xH0001=1",
        status=Achievement.STATUS_DRAFT,
    )
    Achievement.objects.create(
        game=game,
        author=user,
        title="Community One",
        description="c",
        points=10,
        mem_addr="0xH0002=1",
        status=Achievement.STATUS_COMMUNITY,
    )
    Achievement.objects.create(
        game=game,
        author=user,
        title="Verified One",
        description="v",
        points=25,
        mem_addr="0xH0003=1",
        status=Achievement.STATUS_VERIFIED,
    )
    return game


@pytest.mark.django_db
def test_patch_returns_full_set_excluding_drafts(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    response = client.post("/dorequest.php", {"r": "patch", "t": token, "g": game.pk})
    data = response.json()
    assert data["Success"] is True
    achievements = data["PatchData"]["Achievements"]
    assert len(achievements) == 2
    titles = {a["Title"] for a in achievements}
    assert titles == {"Community One", "Verified One"}
    community = next(a for a in achievements if a["Title"] == "Community One")
    verified = next(a for a in achievements if a["Title"] == "Verified One")
    assert community["Flags"] == 5
    assert verified["Flags"] == 3


@pytest.mark.django_db
def test_patch_empty_game(client, authed_user):
    _, token = authed_user
    console = Console.objects.create(ra_id=7, name="NES", short_name="NES")
    game = Game.objects.create(title="Empty Game", console=console)
    response = client.post("/dorequest.php", {"r": "patch", "t": token, "g": game.pk})
    data = response.json()
    assert data["Success"] is True
    assert data["PatchData"]["Achievements"] == []


@pytest.mark.django_db
def test_patch_unknown_game(client, authed_user):
    _, token = authed_user
    response = client.post("/dorequest.php", {"r": "patch", "t": token, "g": 99999})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Unknown game"


@pytest.mark.django_db
def test_patch_missing_game_param(client, authed_user):
    _, token = authed_user
    response = client.post("/dorequest.php", {"r": "patch", "t": token})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Unknown game"


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
    response = client.post("/dorequest.php", {"r": "patch", "t": "z" * 64, "g": game.pk})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_patch_expired_token(client, game_with_achievements):
    game = game_with_achievements
    user = User.objects.create_user(username="expired", password="pw", email="expired@test.com")
    user.api_token = "e" * 64
    user.api_token_expires_at = timezone.now() - timedelta(seconds=1)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    response = client.post("/dorequest.php", {"r": "patch", "t": "e" * 64, "g": game.pk})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_patch_response_shape(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    response = client.post("/dorequest.php", {"r": "patch", "t": token, "g": game.pk})
    patch_data = response.json()["PatchData"]
    assert patch_data["ID"] == game.pk
    assert patch_data["Title"] == game.title
    assert patch_data["ConsoleID"] == game.console.ra_id
    assert patch_data["ImageIcon"] == DEFAULT_GAME_ICON_PATH
    assert "RichPresencePatch" in patch_data
    assert "Achievements" in patch_data
    assert patch_data["Leaderboards"] == []


@pytest.mark.django_db
def test_patch_achievement_shape(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    response = client.post("/dorequest.php", {"r": "patch", "t": token, "g": game.pk})
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
    response = client.post("/dorequest.php", {"r": "patch", "t": token, "g": game.pk})
    for ach in response.json()["PatchData"]["Achievements"]:
        badge = ach["BadgeName"]
        assert len(badge) == 5
        assert badge == f"{ach['ID']:05d}"


@pytest.mark.django_db
def test_patch_rich_presence_passthrough(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    response = client.post("/dorequest.php", {"r": "patch", "t": token, "g": game.pk})
    assert response.json()["PatchData"]["RichPresencePatch"] == game.rich_presence_patch


# --- achievementsets ---


@pytest.mark.django_db
def test_achievementsets_by_hash_returns_core_set(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    gh = GameHash.objects.create(game=game, md5="c" * 32, label="NTSC-US")
    response = client.post("/dorequest.php", {"r": "achievementsets", "t": token, "m": gh.md5})
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
    GameHash.objects.create(game=game_with_achievements, md5="c" * 32, label="NTSC-US")
    response = client.post("/dorequest.php", {"r": "achievementsets", "t": token, "m": "c" * 32})
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
    GameHash.objects.create(game=game, md5="c" * 32, label="NTSC-US")
    response = client.post("/dorequest.php", {"r": "achievementsets", "t": token, "m": "C" * 32})
    assert response.json()["GameId"] == game.pk


@pytest.mark.django_db
def test_achievementsets_by_game_id(client, authed_user, game_with_achievements):
    _, token = authed_user
    game = game_with_achievements
    response = client.post("/dorequest.php", {"r": "achievementsets", "t": token, "g": game.pk})
    assert response.json()["GameId"] == game.pk


@pytest.mark.django_db
def test_achievementsets_unknown_hash_returns_not_found(client, authed_user):
    _, token = authed_user
    response = client.post("/dorequest.php", {"r": "achievementsets", "t": token, "m": "d" * 32})
    data = response.json()
    assert data["Success"] is False
    assert data["Code"] == "not_found"
    assert data["Status"] == 404


@pytest.mark.django_db
def test_achievementsets_without_hash_or_game_id_returns_not_found(client, authed_user):
    _, token = authed_user
    response = client.post("/dorequest.php", {"r": "achievementsets", "t": token})
    data = response.json()
    assert data["Success"] is False
    assert data["Code"] == "not_found"


@pytest.mark.django_db
def test_achievementsets_missing_token(client, game_with_achievements):
    response = client.post("/dorequest.php", {"r": "achievementsets", "m": "c" * 32})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


# --- allprogress ---


@pytest.mark.django_db
def test_allprogress_returns_empty_response(client, authed_user):
    _, token = authed_user
    response = client.post("/dorequest.php", {"r": "allprogress", "t": token, "c": 12})
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
        {"r": "awardachievement", "t": token, "a": achievement.pk, "h": "0"},
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
    payload = {"r": "awardachievement", "t": token, "a": achievement.pk, "h": "0"}
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
        {"r": "awardachievement", "t": token, "a": achievement.pk, "h": "1"},
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
        {"r": "awardachievement", "t": token, "a": achievement.pk, "h": "0"},
    )
    assert response.json()["AchievementsRemaining"] == 1


@pytest.mark.django_db
def test_awardachievement_unknown_achievement(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php", {"r": "awardachievement", "t": token, "a": 99999, "h": "0"}
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Unknown achievement"


@pytest.mark.django_db
def test_awardachievement_invalid_achievement_param(client, authed_user):
    _, token = authed_user
    response = client.post(
        "/dorequest.php", {"r": "awardachievement", "t": token, "a": "abc", "h": "0"}
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Unknown achievement"


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
        {"r": "awardachievement", "t": "z" * 64, "a": achievement.pk, "h": "0"},
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
        "/dorequest.php", {"r": "startsession", "t": "z" * 64, "g": game_with_achievements.pk}
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_startsession_missing_game_param(client, authed_user):
    _, token = authed_user
    response = client.post("/dorequest.php", {"r": "startsession", "t": token})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Unknown game"


@pytest.mark.django_db
def test_startsession_invalid_game_param(client, authed_user):
    _, token = authed_user
    response = client.post("/dorequest.php", {"r": "startsession", "t": token, "g": "abc"})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Unknown game"


@pytest.mark.django_db
def test_startsession_no_unlocks(client, authed_user, game_with_achievements):
    _, token = authed_user
    response = client.post(
        "/dorequest.php", {"r": "startsession", "t": token, "g": game_with_achievements.pk}
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
        {"r": "awardachievement", "t": token, "a": achievement.pk, "h": "0"},
    )
    response = client.post(
        "/dorequest.php", {"r": "startsession", "t": token, "g": game_with_achievements.pk}
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
        {"r": "awardachievement", "t": token, "a": achievement.pk, "h": "1"},
    )
    response = client.post(
        "/dorequest.php", {"r": "startsession", "t": token, "g": game_with_achievements.pk}
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
        {"r": "awardachievement", "t": token, "a": achievement.pk, "h": "0"},
    )
    response = client.post(
        "/dorequest.php", {"r": "startsession", "t": token, "g": game_with_achievements.pk}
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
        "/dorequest.php", {"r": "ping", "t": "z" * 64, "g": game_with_achievements.pk}
    )
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Credentials invalid."


@pytest.mark.django_db
def test_ping_invalid_game_param(client, authed_user):
    _, token = authed_user
    response = client.post("/dorequest.php", {"r": "ping", "t": token, "g": "abc"})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Unknown game"


@pytest.mark.django_db
def test_ping_stores_rich_presence(client, authed_user, game_with_achievements):
    user, token = authed_user
    game = game_with_achievements
    response = client.post(
        "/dorequest.php",
        {"r": "ping", "t": token, "g": game.pk, "m": "No N. Sanity Beach"},
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
            {"r": "ping", "t": token, "g": game.pk, "m": "No N. Sanity Beach"},
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
    user.api_token_expires_at = timezone.now() + timedelta(days=14)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    return user


@pytest.mark.django_db
def test_patch_serializes_leaderboard(client, authed_user, game_with_leaderboards):
    _, token = authed_user
    game, lb = game_with_leaderboards
    response = client.post("/dorequest.php", {"r": "patch", "t": token, "g": game.pk})
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
    GameHash.objects.create(game=game, md5="d" * 32, label="NTSC-US")
    response = client.post("/dorequest.php", {"r": "achievementsets", "t": token, "m": "d" * 32})
    leaderboards = response.json()["Sets"][0]["Leaderboards"]
    assert len(leaderboards) == 1
    assert leaderboards[0]["ID"] == lb.id
    assert leaderboards[0]["Mem"] == LEADERBOARD_MEM


@pytest.mark.django_db
def test_submitlbentry_creates_entry(client, authed_user, game_with_leaderboards):
    user, token = authed_user
    _, lb = game_with_leaderboards
    response = client.post(
        "/dorequest.php", {"r": "submitlbentry", "t": token, "i": lb.id, "s": 1234}
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
    client.post("/dorequest.php", {"r": "submitlbentry", "t": token, "i": lb.id, "s": 500})
    response = client.post(
        "/dorequest.php", {"r": "submitlbentry", "t": token, "i": lb.id, "s": 900}
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
    client.post("/dorequest.php", {"r": "submitlbentry", "t": token, "i": lb.id, "s": 900})
    response = client.post(
        "/dorequest.php", {"r": "submitlbentry", "t": token, "i": lb.id, "s": 500}
    )
    assert response.json()["Response"]["BestScore"] == 500
    assert LeaderboardEntry.objects.get(leaderboard=lb, user=user).score == 500


@pytest.mark.django_db
def test_submitlbentry_top_entries_and_rank(client, authed_user, game_with_leaderboards):
    _, token = authed_user
    game, lb = game_with_leaderboards
    rival = _make_user("rival", "r" * 64)
    LeaderboardEntry.objects.create(leaderboard=lb, user=rival, score=300)
    response = client.post(
        "/dorequest.php", {"r": "submitlbentry", "t": token, "i": lb.id, "s": 800}
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
def test_submitlbentry_unknown_leaderboard(client, authed_user):
    _, token = authed_user
    response = client.post("/dorequest.php", {"r": "submitlbentry", "t": token, "i": 999, "s": 1})
    data = response.json()
    assert data["Success"] is False
    assert data["Error"] == "Unknown leaderboard"


@pytest.mark.django_db
def test_submitlbentry_invalid_score(client, authed_user, game_with_leaderboards):
    _, token = authed_user
    _, lb = game_with_leaderboards
    response = client.post(
        "/dorequest.php", {"r": "submitlbentry", "t": token, "i": lb.id, "s": "abc"}
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
