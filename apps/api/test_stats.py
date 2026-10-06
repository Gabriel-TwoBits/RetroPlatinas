"""The public stats JSON API: user summary and recent unlocks, game leaderboards and players."""

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.achievements.models import Achievement, UserUnlock
from apps.api.views import GAME_PLAYERS_LIMIT, LEADERBOARD_TOP_LIMIT, RECENT_UNLOCKS_LIMIT
from apps.games.models import Console, Game, PlayerGame
from apps.leaderboards.models import Leaderboard, LeaderboardEntry

User = get_user_model()

PLAYSTATION_RA_ID = 12
# Postgres' bigint ends at 2**63 - 1: a larger id in the path must answer 404, not a server error.
ID_PAST_BIGINT = 2**63
SYSTEM_ACCOUNT = "ra-import"
# Added to an existing id to name a row that does not exist.
UNKNOWN_ID_OFFSET = 1000
VETERAN_PLAYTIME_SECONDS = int(timedelta(hours=2).total_seconds())
NEWCOMER_PLAYTIME_SECONDS = int(timedelta(minutes=1).total_seconds())

# Each query-count test holds its count while the rows grow: a query per row would break it.
USER_SUMMARY_QUERIES = 4
RECENT_UNLOCKS_QUERIES = 2
LEADERBOARD_QUERIES = 5
GAME_PLAYERS_QUERIES = 4


def _user(username, hardcore_points=0, softcore_points=0, is_active=True):
    return User.objects.create(
        username=username,
        hardcore_points=hardcore_points,
        softcore_points=softcore_points,
        is_active=is_active,
    )


def _achievement(game, title, points=5, status=Achievement.STATUS_COMMUNITY):
    return Achievement.objects.create(
        game=game,
        author=User.objects.get(username=SYSTEM_ACCOUNT),
        title=title,
        description=f"{title} description",
        points=points,
        mem_addr="0xH0001=1",
        status=status,
    )


def _unlock(user, achievement, hardcore, unlocked_at):
    """Records an unlock as `handle_awardachievement` does: hardcore writes the softcore twin."""
    UserUnlock.objects.create(
        user=user, achievement=achievement, hardcore=False, unlocked_at=unlocked_at
    )
    if hardcore:
        UserUnlock.objects.create(
            user=user, achievement=achievement, hardcore=True, unlocked_at=unlocked_at
        )


@pytest.fixture
def crash(db):
    _user(SYSTEM_ACCOUNT, is_active=False)
    console = Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


@pytest.fixture
def ape_escape(crash):
    return Game.objects.create(title="Ape Escape", console=crash.console)


# --- /api/users/<username>/ ---


@pytest.mark.django_db
def test_user_summary_reports_points_ranks_games_and_unlocks(client, crash, ape_escape):
    player = _user("player", hardcore_points=10, softcore_points=15)
    _user("leader", hardcore_points=50, softcore_points=50)
    _user("tied", hardcore_points=10, softcore_points=40)
    # Inactive accounts hold no rank, however many points they have.
    _user("banned", hardcore_points=999, softcore_points=999, is_active=False)
    now = timezone.now()
    hardcore = _achievement(crash, "Hardcore one", points=10)
    softcore = _achievement(crash, "Softcore one", points=5)
    draft = _achievement(crash, "Draft", status=Achievement.STATUS_DRAFT)
    _unlock(player, hardcore, hardcore=True, unlocked_at=now)
    _unlock(player, softcore, hardcore=False, unlocked_at=now)
    _unlock(player, draft, hardcore=True, unlocked_at=now)
    PlayerGame.objects.create(user=player, game=crash)
    PlayerGame.objects.create(user=player, game=ape_escape)

    response = client.get("/api/users/player/")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "User": "player",
        "Points": {"Hardcore": 10, "Softcore": 15},
        "Rank": {"Hardcore": 2, "Softcore": 3},
        "GamesPlayed": 2,
        "AchievementsUnlocked": {"Hardcore": 1, "Softcore": 2},
    }


@pytest.mark.django_db
def test_user_summary_ranks_ties_together(client, crash):
    _user("first", hardcore_points=20, softcore_points=20)
    _user("second", hardcore_points=20, softcore_points=20)
    _user("third", hardcore_points=5, softcore_points=5)

    ranks = [
        client.get(f"/api/users/{name}/").json()["Rank"] for name in ("first", "second", "third")
    ]

    assert ranks == [
        {"Hardcore": 1, "Softcore": 1},
        {"Hardcore": 1, "Softcore": 1},
        {"Hardcore": 3, "Softcore": 3},
    ]


@pytest.mark.django_db
def test_user_summary_leaves_users_without_points_unranked(client, crash):
    _user("softcore-only", hardcore_points=0, softcore_points=5)

    data = client.get("/api/users/softcore-only/").json()

    assert data["Rank"] == {"Hardcore": None, "Softcore": 1}


@pytest.mark.django_db
def test_user_summary_leaves_inactive_users_unranked(client, crash):
    response = client.get(f"/api/users/{SYSTEM_ACCOUNT}/")

    assert response.status_code == HTTPStatus.OK
    assert response.json()["Rank"] == {"Hardcore": None, "Softcore": None}


@pytest.mark.django_db
def test_user_summary_unknown_user_answers_404(client, crash):
    response = client.get("/api/users/nobody/")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {"Error": "Unknown user nobody."}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/api/users/player/",
        "/api/users/player/recent/",
        "/api/games/1/leaderboard/1/",
        "/api/games/1/players/",
    ],
)
def test_stats_endpoints_reject_post(client, crash, path):
    _user("player")

    response = client.post(path)

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_user_summary_query_count_does_not_grow_with_unlocks(
    client, crash, ape_escape, django_assert_num_queries
):
    player = _user("player", hardcore_points=10, softcore_points=10)
    now = timezone.now()
    for index in range(RECENT_UNLOCKS_LIMIT):
        _unlock(player, _achievement(crash, f"A{index}"), hardcore=True, unlocked_at=now)
    PlayerGame.objects.create(user=player, game=crash)
    PlayerGame.objects.create(user=player, game=ape_escape)

    with django_assert_num_queries(USER_SUMMARY_QUERIES):
        response = client.get("/api/users/player/")

    assert response.json()["AchievementsUnlocked"] == {
        "Hardcore": RECENT_UNLOCKS_LIMIT,
        "Softcore": RECENT_UNLOCKS_LIMIT,
    }


# --- /api/users/<username>/recent/ ---


@pytest.mark.django_db
def test_recent_unlocks_newest_first_one_entry_per_unlock(client, crash, ape_escape):
    player = _user("player")
    now = timezone.now()
    beach = _achievement(crash, "Beach", points=5)
    jungle = _achievement(crash, "Jungle", points=10)
    monkey = _achievement(ape_escape, "Monkey", points=25)
    draft = _achievement(crash, "Draft", status=Achievement.STATUS_DRAFT)
    _unlock(player, beach, hardcore=False, unlocked_at=now - timedelta(hours=3))
    # A later hardcore unlock of an achievement already unlocked in softcore is its own unlock.
    UserUnlock.objects.create(
        user=player, achievement=beach, hardcore=True, unlocked_at=now - timedelta(hours=1)
    )
    _unlock(player, jungle, hardcore=True, unlocked_at=now - timedelta(hours=2))
    _unlock(player, monkey, hardcore=False, unlocked_at=now)
    _unlock(player, draft, hardcore=True, unlocked_at=now)

    response = client.get("/api/users/player/recent/")

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["User"] == "player"
    assert [(u["Title"], u["Hardcore"]) for u in data["Unlocks"]] == [
        ("Monkey", False),
        ("Beach", True),
        ("Jungle", True),
        ("Beach", False),
    ]
    monkey_entry = data["Unlocks"][0]
    assert monkey_entry["AchievementID"] == monkey.pk
    assert monkey_entry["Description"] == "Monkey description"
    assert monkey_entry["Points"] == monkey.points
    assert monkey_entry["GameID"] == ape_escape.pk
    assert monkey_entry["GameTitle"] == "Ape Escape"
    assert monkey_entry["UnlockedAt"] == now.isoformat()
    assert monkey_entry["BadgeURL"].startswith("http://testserver/Badge/")


@pytest.mark.django_db
def test_recent_unlocks_keeps_the_latest_twenty_in_constant_queries(
    client, crash, django_assert_num_queries
):
    player = _user("player")
    now = timezone.now()
    extra_unlocks = 5
    for minutes_ago in range(RECENT_UNLOCKS_LIMIT + extra_unlocks):
        _unlock(
            player,
            _achievement(crash, f"A{minutes_ago}"),
            hardcore=True,
            unlocked_at=now - timedelta(minutes=minutes_ago),
        )

    with django_assert_num_queries(RECENT_UNLOCKS_QUERIES):
        response = client.get("/api/users/player/recent/")

    titles = [unlock["Title"] for unlock in response.json()["Unlocks"]]
    assert titles == [f"A{minutes_ago}" for minutes_ago in range(RECENT_UNLOCKS_LIMIT)]


@pytest.mark.django_db
def test_recent_unlocks_unknown_user_answers_404(client, crash):
    response = client.get("/api/users/nobody/recent/")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {"Error": "Unknown user nobody."}


# --- /api/games/<id>/leaderboard/<lb_id>/ ---


@pytest.fixture
def fastest_beach(crash):
    return Leaderboard.objects.create(
        game=crash,
        title="Fastest beach",
        description="Clear N. Sanity Beach",
        mem_addr="STA:0xH1=1::CAN:0xH2=1::SUB:0xH3=1::VAL:0xH4",
        format=Leaderboard.Format.FRAMES,
        lower_is_better=True,
    )


@pytest.mark.django_db
def test_leaderboard_ranks_active_entries_with_raw_scores(client, crash, fastest_beach):
    for username, score in [("slow", 900), ("fast", 300), ("tied", 300), ("middle", 500)]:
        LeaderboardEntry.objects.create(
            leaderboard=fastest_beach, user=_user(username), score=score
        )
    LeaderboardEntry.objects.create(
        leaderboard=fastest_beach, user=_user("banned", is_active=False), score=1
    )

    response = client.get(f"/api/games/{crash.pk}/leaderboard/{fastest_beach.pk}/")

    assert response.status_code == HTTPStatus.OK
    data = response.json()
    assert data["GameID"] == crash.pk
    assert data["LeaderboardID"] == fastest_beach.pk
    assert data["Title"] == "Fastest beach"
    assert data["Description"] == "Clear N. Sanity Beach"
    assert data["Format"] == "FRAMES"
    assert data["LowerIsBetter"] is True
    assert data["TotalEntries"] == 4
    assert [(e["Rank"], e["User"], e["Score"]) for e in data["Entries"]] == [
        (1, "fast", 300),
        (1, "tied", 300),
        (3, "middle", 500),
        (4, "slow", 900),
    ]


@pytest.mark.django_db
def test_leaderboard_higher_is_better_puts_the_highest_first(client, crash, fastest_beach):
    fastest_beach.lower_is_better = False
    fastest_beach.save(update_fields=["lower_is_better"])
    for username, score in [("low", 10), ("high", 30)]:
        LeaderboardEntry.objects.create(
            leaderboard=fastest_beach, user=_user(username), score=score
        )

    data = client.get(f"/api/games/{crash.pk}/leaderboard/{fastest_beach.pk}/").json()

    assert [(e["Rank"], e["User"]) for e in data["Entries"]] == [(1, "high"), (2, "low")]


@pytest.mark.django_db
def test_leaderboard_serves_the_top_hundred_in_constant_queries(
    client, crash, fastest_beach, django_assert_num_queries
):
    extra_entries = 5
    for index in range(LEADERBOARD_TOP_LIMIT + extra_entries):
        LeaderboardEntry.objects.create(
            leaderboard=fastest_beach, user=_user(f"player{index}"), score=index
        )

    with django_assert_num_queries(LEADERBOARD_QUERIES):
        response = client.get(f"/api/games/{crash.pk}/leaderboard/{fastest_beach.pk}/")

    data = response.json()
    assert data["TotalEntries"] == LEADERBOARD_TOP_LIMIT + extra_entries
    assert len(data["Entries"]) == LEADERBOARD_TOP_LIMIT
    assert data["Entries"][-1]["Rank"] == LEADERBOARD_TOP_LIMIT


@pytest.mark.django_db
def test_leaderboard_unknown_game_answers_404(client, crash, fastest_beach):
    for game_id in (crash.pk + UNKNOWN_ID_OFFSET, ID_PAST_BIGINT):
        response = client.get(f"/api/games/{game_id}/leaderboard/{fastest_beach.pk}/")

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.json() == {"Error": f"Unknown game {game_id}."}


@pytest.mark.django_db
def test_leaderboard_unknown_leaderboard_answers_404(client, crash, fastest_beach):
    unknown_id = fastest_beach.pk + UNKNOWN_ID_OFFSET

    response = client.get(f"/api/games/{crash.pk}/leaderboard/{unknown_id}/")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {"Error": f"Unknown leaderboard {unknown_id}."}


@pytest.mark.django_db
def test_leaderboard_of_another_game_answers_404(client, crash, ape_escape, fastest_beach):
    response = client.get(f"/api/games/{ape_escape.pk}/leaderboard/{fastest_beach.pk}/")

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert response.json() == {"Error": f"Unknown leaderboard {fastest_beach.pk}."}


# --- /api/games/<id>/players/ ---


@pytest.mark.django_db
def test_game_players_most_recent_first_with_progress(client, crash, ape_escape):
    now = timezone.now()
    hardcore = _achievement(crash, "Hardcore one")
    softcore = _achievement(crash, "Softcore one")
    draft = _achievement(crash, "Draft", status=Achievement.STATUS_DRAFT)
    monkey = _achievement(ape_escape, "Monkey")
    veteran = _user("veteran")
    newcomer = _user("newcomer")
    PlayerGame.objects.create(
        user=veteran,
        game=crash,
        first_played_at=now - timedelta(days=30),
        last_played_at=now - timedelta(days=1),
        playtime_seconds=VETERAN_PLAYTIME_SECONDS,
    )
    PlayerGame.objects.create(
        user=newcomer,
        game=crash,
        first_played_at=now,
        last_played_at=now,
        playtime_seconds=NEWCOMER_PLAYTIME_SECONDS,
    )
    PlayerGame.objects.create(user=_user("banned", is_active=False), game=crash)
    PlayerGame.objects.create(user=_user("elsewhere"), game=ape_escape)
    _unlock(veteran, hardcore, hardcore=True, unlocked_at=now)
    _unlock(veteran, softcore, hardcore=False, unlocked_at=now)
    _unlock(veteran, draft, hardcore=True, unlocked_at=now)
    _unlock(veteran, monkey, hardcore=True, unlocked_at=now)

    response = client.get(f"/api/games/{crash.pk}/players/")

    assert response.status_code == HTTPStatus.OK
    assert response.json() == {
        "GameID": crash.pk,
        "Title": "Crash Bandicoot",
        "AchievementsTotal": 2,
        "TotalPlayers": 2,
        "Players": [
            {
                "User": "newcomer",
                "FirstPlayedAt": now.isoformat(),
                "LastPlayedAt": now.isoformat(),
                "PlaytimeSeconds": NEWCOMER_PLAYTIME_SECONDS,
                "AchievementsUnlocked": {"Hardcore": 0, "Softcore": 0},
            },
            {
                "User": "veteran",
                "FirstPlayedAt": (now - timedelta(days=30)).isoformat(),
                "LastPlayedAt": (now - timedelta(days=1)).isoformat(),
                "PlaytimeSeconds": VETERAN_PLAYTIME_SECONDS,
                "AchievementsUnlocked": {"Hardcore": 1, "Softcore": 2},
            },
        ],
    }


@pytest.mark.django_db
def test_game_players_lists_the_most_recent_in_constant_queries(
    client, crash, django_assert_num_queries
):
    now = timezone.now()
    achievement = _achievement(crash, "Beach")
    extra_players = 5
    for minutes_ago in range(GAME_PLAYERS_LIMIT + extra_players):
        player = _user(f"player{minutes_ago}")
        PlayerGame.objects.create(
            user=player, game=crash, last_played_at=now - timedelta(minutes=minutes_ago)
        )
        _unlock(player, achievement, hardcore=True, unlocked_at=now)

    with django_assert_num_queries(GAME_PLAYERS_QUERIES):
        response = client.get(f"/api/games/{crash.pk}/players/")

    data = response.json()
    assert data["TotalPlayers"] == GAME_PLAYERS_LIMIT + extra_players
    assert [p["User"] for p in data["Players"]] == [
        f"player{minutes_ago}" for minutes_ago in range(GAME_PLAYERS_LIMIT)
    ]
    assert {p["AchievementsUnlocked"]["Hardcore"] for p in data["Players"]} == {1}


@pytest.mark.django_db
def test_game_players_unknown_game_answers_404(client, crash):
    for game_id in (crash.pk + UNKNOWN_ID_OFFSET, ID_PAST_BIGINT):
        response = client.get(f"/api/games/{game_id}/players/")

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.json() == {"Error": f"Unknown game {game_id}."}
