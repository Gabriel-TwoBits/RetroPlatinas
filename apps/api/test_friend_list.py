"""`getfriendlist`: the users the token's user follows, in the shape rcheevos v12.4.0 parses
(`rc_api_process_fetch_followed_users_server_response` in `rc_api_user.c`)."""

from datetime import timedelta
from http import HTTPStatus
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import Friendship
from apps.api.handlers import API_TOKEN_LIFETIME, LAST_SEEN_UNKNOWN
from apps.games.models import Console, Game, PlayerGame
from apps.images.catalog import avatar_path, versioned_game_icon_path

User = get_user_model()

FORM = "application/x-www-form-urlencoded"
PLAYER = "player"
PLAYER_TOKEN = "tok"
# The request body rcheevos' `rc_api_init_fetch_followed_users_request` builds.
RCHEEVOS_GET_FRIEND_LIST = "r=getfriendlist&u=player&t=tok"
PLAYSTATION_RA_ID = 12
HARDCORE_POINTS = 1234
SOFTCORE_POINTS = 2345
SMALL_CAP = 2
# Ages of play records, in minutes.
EARLIER_MINUTES_AGO = 30
LATEST_MINUTES_AGO = 5
# Every key rcheevos reads from a `Friends` entry.
FRIEND_FIELDS = {
    "Friend",
    "AvatarUrl",
    "RAPoints",
    "LastSeen",
    "LastSeenTime",
    "LastGameId",
    "LastGameTitle",
    "LastGameIconUrl",
}
INVALID_CREDENTIALS = {
    "Success": False,
    "Error": "Credentials invalid.",
    "Status": HTTPStatus.UNAUTHORIZED,
    "Code": "invalid_credentials",
}
EXPIRED_TOKEN = {
    "Success": False,
    "Error": "The access token has expired. Please log in again.",
    "Status": HTTPStatus.UNAUTHORIZED,
    "Code": "expired_token",
}


def _user(username, **fields):
    return User.objects.create_user(username=username, password="pw", **fields)


def _friend(player, username, **fields):
    friend = _user(username, **fields)
    Friendship.objects.create(user=player, friend=friend)
    return friend


def _friend_list(client, body=RCHEEVOS_GET_FRIEND_LIST):
    return client.post("/dorequest.php", body, content_type=FORM).json()


def _names(data):
    return [entry["Friend"] for entry in data["Friends"]]


def _play(user, game, minutes_ago, rich_presence="", pinged=True):
    seen_at = timezone.now() - timedelta(minutes=minutes_ago)
    return PlayerGame.objects.create(
        user=user,
        game=game,
        last_played_at=seen_at,
        last_ping_at=seen_at if pinged else None,
        last_rich_presence=rich_presence,
    )


@pytest.fixture
def player(db):
    user = _user(PLAYER)
    user.api_token = PLAYER_TOKEN
    user.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    user.save(update_fields=["api_token", "api_token_expires_at"])
    return user


@pytest.fixture
def playstation(db):
    return Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")


@pytest.fixture
def crash(playstation):
    return Game.objects.create(title="Crash Bandicoot", console=playstation)


@pytest.fixture
def spyro(playstation):
    return Game.objects.create(title="Spyro the Dragon", console=playstation)


@pytest.mark.django_db
def test_getfriendlist_serves_each_followed_user_with_the_latest_play(client, player, crash, spyro):
    friend = _friend(
        player, "friend", hardcore_points=HARDCORE_POINTS, softcore_points=SOFTCORE_POINTS
    )
    _play(friend, crash, minutes_ago=EARLIER_MINUTES_AGO, rich_presence="Old presence")
    latest = _play(
        friend, spyro, minutes_ago=LATEST_MINUTES_AGO, rich_presence="Stone Hill, 3 dragons"
    )

    data = _friend_list(client)

    assert data == {
        "Success": True,
        "Friends": [
            {
                "Friend": "friend",
                "AvatarUrl": f"http://testserver{avatar_path('friend')}",
                "RAPoints": HARDCORE_POINTS,
                "LastSeen": "Stone Hill, 3 dragons",
                "LastSeenTime": int(latest.last_ping_at.timestamp()),
                "LastGameId": spyro.pk,
                "LastGameTitle": "Spyro the Dragon",
                "LastGameIconUrl": f"http://testserver{versioned_game_icon_path(spyro)}",
            }
        ],
    }
    assert set(data["Friends"][0]) == FRIEND_FIELDS


@pytest.mark.django_db
def test_getfriendlist_nulls_the_last_seen_fields_of_a_friend_who_never_played(client, player):
    _friend(player, "newcomer")

    entry = _friend_list(client)["Friends"][0]

    assert entry["LastSeen"] == LAST_SEEN_UNKNOWN
    assert entry["LastSeenTime"] is None
    assert entry["LastGameId"] is None
    assert entry["LastGameTitle"] is None
    assert entry["LastGameIconUrl"] is None
    assert set(entry) == FRIEND_FIELDS


@pytest.mark.django_db
def test_getfriendlist_dates_a_session_without_pings_by_its_start_and_unknown_presence(
    client, player, crash
):
    friend = _friend(player, "friend")
    record = _play(friend, crash, minutes_ago=LATEST_MINUTES_AGO, pinged=False)

    entry = _friend_list(client)["Friends"][0]

    assert entry["LastSeen"] == LAST_SEEN_UNKNOWN
    assert entry["LastSeenTime"] == int(record.last_played_at.timestamp())
    assert entry["LastGameId"] == crash.pk


@pytest.mark.django_db
def test_getfriendlist_orders_by_last_seen_then_hardcore_points(client, player, crash):
    _friend(player, "never-low")
    _friend(player, "never-high", hardcore_points=HARDCORE_POINTS)
    _play(_friend(player, "earlier"), crash, minutes_ago=EARLIER_MINUTES_AGO)
    _play(_friend(player, "latest"), crash, minutes_ago=1)

    assert _names(_friend_list(client)) == ["latest", "earlier", "never-high", "never-low"]


@pytest.mark.django_db
def test_getfriendlist_lists_only_active_users_the_player_follows(client, player, crash):
    _friend(player, "friend")
    _friend(player, "banned", is_active=False)
    follower = _user("follower")
    Friendship.objects.create(user=follower, friend=player)
    _user("stranger")

    assert _names(_friend_list(client)) == ["friend"]


@pytest.mark.django_db
def test_getfriendlist_serves_at_most_the_cap_most_recently_seen(client, player, crash):
    for minutes_ago in range(SMALL_CAP + 1):
        _play(_friend(player, f"friend{minutes_ago}"), crash, minutes_ago=minutes_ago)

    with patch("apps.api.handlers.FRIEND_LIST_MAX", SMALL_CAP):
        names = _names(_friend_list(client))

    assert names == ["friend0", "friend1"]


@pytest.mark.django_db
def test_getfriendlist_without_follows_is_an_empty_list(client, player):
    assert _friend_list(client) == {"Success": True, "Friends": []}


@pytest.mark.django_db
def test_getfriendlist_queries_do_not_grow_with_friends(client, player, crash, spyro):
    def query_count():
        with CaptureQueriesContext(connection) as queries:
            _friend_list(client)
        return len(queries)

    _play(_friend(player, "first"), crash, minutes_ago=1)
    baseline = query_count()

    for index, game in enumerate([crash, spyro]):
        _play(_friend(player, f"more{index}"), game, minutes_ago=index)
    _friend(player, "idle")

    assert query_count() == baseline


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body",
    [
        "r=getfriendlist&u=player&t=wrong",
        "r=getfriendlist&u=other&t=tok",
        "r=getfriendlist&u=player",
    ],
)
def test_getfriendlist_needs_the_users_live_token(client, player, body):
    _user("other")
    assert _friend_list(client, body) == INVALID_CREDENTIALS


@pytest.mark.django_db
def test_getfriendlist_reports_an_expired_token(client, player):
    User.objects.filter(pk=player.pk).update(api_token_expires_at=timezone.now())
    assert _friend_list(client) == EXPIRED_TOKEN
