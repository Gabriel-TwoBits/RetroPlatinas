from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.games.models import (
    MD5_HEX_DIGITS,
    PLAYING_NOW_TTL,
    PLAYTIME_MAX_PING_GAP,
    RC_CLIENT_PING_INTERVAL,
    Console,
    Game,
    GameHash,
    PlayerGame,
)

CRASH_MD5_UPPERCASE = "35386FD0891E594C9B6D8A4A5BAA0027"
PLAYSTATION_RA_ID = 12
CONSOLES_IN_FIXTURE = 10


@pytest.fixture
def console():
    return Console.objects.create(ra_id=12, name="PlayStation", short_name="PS1")


@pytest.mark.django_db
def test_console_str(console):
    assert str(console) == "PlayStation"


@pytest.mark.django_db
def test_game_and_hash_creation(console):
    game = Game.objects.create(title="Crash Bandicoot", console=console)
    gh = GameHash.objects.create(game=game, md5="a" * MD5_HEX_DIGITS, label="NTSC-US")

    assert str(game) == "Crash Bandicoot"
    assert str(gh) == f"NTSC-US ({'a' * MD5_HEX_DIGITS})"
    assert game.hashes.count() == 1


@pytest.mark.django_db
def test_loaddata_consoles():
    call_command("loaddata", "consoles", verbosity=0)
    assert Console.objects.count() == CONSOLES_IN_FIXTURE


@pytest.mark.django_db(transaction=True, reset_sequences=True)
def test_loaddata_consoles_after_a_seed_keeps_the_seeded_console():
    playstation = Console.objects.create(
        ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1"
    )
    game = Game.objects.create(title="Crash Bandicoot", console=playstation)

    call_command("loaddata", "consoles", verbosity=0)
    call_command("loaddata", "consoles", verbosity=0)

    game.refresh_from_db()
    assert game.console.pk == playstation.pk
    assert game.console.ra_id == PLAYSTATION_RA_ID
    assert Console.objects.count() == CONSOLES_IN_FIXTURE


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


@pytest.mark.django_db
def test_admin_inline_rejects_hashes_differing_only_in_case(client, console):
    admin = get_user_model().objects.create_superuser(
        username="admin", email="admin@example.com", password="pw-secret-123"
    )
    client.force_login(admin)
    resp = client.post(
        "/admin/games/game/add/",
        {
            "title": "Crash Bandicoot",
            "console": console.pk,
            "hashes-TOTAL_FORMS": "2",
            "hashes-INITIAL_FORMS": "0",
            "hashes-0-md5": CRASH_MD5_UPPERCASE,
            "hashes-0-label": "NTSC-US",
            "hashes-1-md5": CRASH_MD5_UPPERCASE.lower(),
            "hashes-1-label": "NTSC-US copy",
        },
    )
    assert resp.status_code == 200
    assert resp.context["inline_admin_formsets"][0].formset.non_form_errors()
    assert not Game.objects.exists()
    assert not GameHash.objects.exists()


# --- PlayerGame ---

ONE_SECOND = timedelta(seconds=1)


@pytest.fixture
def player_game(console):
    user = get_user_model().objects.create_user(username="player", password="pw")
    game = Game.objects.create(title="Crash Bandicoot", console=console)
    return PlayerGame.objects.create(user=user, game=game)


def test_ping_gap_spans_more_than_one_ping_and_ends_within_the_ttl():
    assert RC_CLIENT_PING_INTERVAL < PLAYTIME_MAX_PING_GAP <= PLAYING_NOW_TTL


def test_playing_now_ttl_is_five_minutes():
    assert PLAYING_NOW_TTL == timedelta(minutes=5)


@pytest.mark.django_db
def test_player_game_is_unique_per_user_and_game(player_game):
    with pytest.raises(IntegrityError):
        PlayerGame.objects.create(user=player_game.user, game=player_game.game)


PLAYER_GAME_ADMIN_URL = "/admin/games/playergame/"


@pytest.mark.django_db
def test_player_game_admin_is_view_only(admin_client, player_game):
    row_url = f"{PLAYER_GAME_ADMIN_URL}{player_game.pk}/"

    assert admin_client.get(f"{row_url}change/").status_code == HTTPStatus.OK
    assert admin_client.get(f"{row_url}delete/").status_code == HTTPStatus.FORBIDDEN
    assert admin_client.get(f"{PLAYER_GAME_ADMIN_URL}add/").status_code == HTTPStatus.FORBIDDEN
    assert PlayerGame.objects.filter(pk=player_game.pk).exists()


@pytest.mark.django_db
def test_first_ping_credits_no_playtime(player_game):
    now = timezone.now()

    player_game.record_ping(now)

    assert player_game.playtime_seconds == 0
    assert player_game.last_ping_at == now


@pytest.mark.django_db
def test_ping_credits_the_time_since_the_previous_ping(player_game):
    previous = timezone.now()
    player_game.record_ping(previous)

    player_game.record_ping(previous + RC_CLIENT_PING_INTERVAL)

    assert player_game.playtime_seconds == RC_CLIENT_PING_INTERVAL.total_seconds()


@pytest.mark.django_db
def test_ping_credits_a_gap_of_exactly_the_maximum(player_game):
    previous = timezone.now()
    player_game.record_ping(previous)

    player_game.record_ping(previous + PLAYTIME_MAX_PING_GAP)

    assert player_game.playtime_seconds == PLAYTIME_MAX_PING_GAP.total_seconds()


@pytest.mark.django_db
def test_ping_after_a_longer_gap_credits_nothing_but_restarts_the_count(player_game):
    previous = timezone.now()
    player_game.record_ping(previous)
    resumed = previous + PLAYTIME_MAX_PING_GAP + ONE_SECOND

    player_game.record_ping(resumed)
    assert player_game.playtime_seconds == 0

    player_game.record_ping(resumed + RC_CLIENT_PING_INTERVAL)
    assert player_game.playtime_seconds == RC_CLIENT_PING_INTERVAL.total_seconds()


@pytest.mark.django_db
def test_ping_earlier_than_the_previous_credits_nothing(player_game):
    previous = timezone.now()
    player_game.record_ping(previous)

    player_game.record_ping(previous - ONE_SECOND)

    assert player_game.playtime_seconds == 0


@pytest.mark.django_db
def test_session_start_credits_nothing_and_clears_the_presence(player_game):
    previous = timezone.now()
    player_game.record_ping(previous)
    player_game.last_rich_presence = "Previous session"
    started = previous + RC_CLIENT_PING_INTERVAL

    player_game.start_session(started)

    assert player_game.playtime_seconds == 0
    assert player_game.last_rich_presence == ""
    assert player_game.last_ping_at == started
    assert player_game.last_played_at == started
    assert player_game.session_started_at == started

    player_game.record_ping(started + RC_CLIENT_PING_INTERVAL)
    assert player_game.playtime_seconds == RC_CLIENT_PING_INTERVAL.total_seconds()


@pytest.mark.django_db
def test_playing_now_keeps_sessions_pinged_within_the_ttl(player_game):
    player_game.last_ping_at = timezone.now() - PLAYING_NOW_TTL + ONE_SECOND
    player_game.save()

    assert list(PlayerGame.objects.playing_now()) == [player_game]


@pytest.mark.django_db
def test_playing_now_drops_sessions_past_the_ttl(player_game):
    player_game.last_ping_at = timezone.now() - PLAYING_NOW_TTL - ONE_SECOND
    player_game.save()

    assert not PlayerGame.objects.playing_now().exists()


@pytest.mark.django_db
def test_playing_now_drops_sessions_never_pinged(player_game):
    assert player_game.last_ping_at is None
    assert not PlayerGame.objects.playing_now().exists()


BEFORE_PLAYER_GAME = [("games", "0001_initial")]
AFTER_PLAYER_GAME = [("games", "0002_player_game")]
# The unlock schema the backfill reads, the dependency it declares.
BACKFILL_SOURCE = [("achievements", "0003_achievement_type")]


@pytest.fixture
def restores_latest_schema():
    """Migrates forward again afterwards, so later tests see the current schema."""
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
def test_player_game_migration_backfills_players_from_their_unlocks(restores_latest_schema):
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE_PLAYER_GAME + BACKFILL_SOURCE)
    old_apps = executor.loader.project_state(BEFORE_PLAYER_GAME + BACKFILL_SOURCE).apps
    user = old_apps.get_model("accounts", "User").objects.create(username="player")
    console = old_apps.get_model("games", "Console").objects.create(
        ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1"
    )
    game = old_apps.get_model("games", "Game").objects.create(title="Crash", console=console)
    Achievement = old_apps.get_model("achievements", "Achievement")
    UserUnlock = old_apps.get_model("achievements", "UserUnlock")
    unlocks = [
        UserUnlock.objects.create(
            user=user,
            achievement=Achievement.objects.create(
                game=game, author=user, title=title, description="d", mem_addr="0xH0001=1"
            ),
        )
        for title in ("First", "Second")
    ]

    executor = MigrationExecutor(connection)
    executor.migrate(AFTER_PLAYER_GAME)
    # Later migrations add PlayerGame columns this schema does not have yet.
    HistoricalPlayerGame = executor.loader.project_state(AFTER_PLAYER_GAME).apps.get_model(
        "games", "PlayerGame"
    )

    player_game = HistoricalPlayerGame.objects.get()
    assert (player_game.user_id, player_game.game_id) == (user.pk, game.pk)
    assert player_game.first_played_at == unlocks[0].unlocked_at
    assert player_game.last_played_at == unlocks[1].unlocked_at
    assert player_game.playtime_seconds == 0
