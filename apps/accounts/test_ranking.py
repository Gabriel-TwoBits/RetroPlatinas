"""The global ranking page: active users with points, most first, per mode, a page at a time, and
the cached board shared by every viewer."""

import re
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone

from apps.accounts.ranking import USERS_PER_PAGE
from apps.achievements.models import Achievement, UserUnlock
from apps.games.models import Console, Game
from apps.images.catalog import avatar_path

User = get_user_model()

RANKING = "/ranking/"
PLAYSTATION_RA_ID = 12
SYSTEM_ACCOUNT = "ra-import"
PASSWORD = "pw-secret-123"
ROW = re.compile(
    r'<li class="[^"]*">\s*<div[^>]*>(\d+)</div>.*?href="/users/([^/"]+)/"(.*?)</li>', re.DOTALL
)
# More users than one page holds, so the cut is visible.
EXTRA_USERS = 2
# Enough users that a per-row query would show in the count.
LARGE_SITE_USERS = 1_050
UNLOCKING_USERS = 300
LARGE_SITE_ACHIEVEMENTS = 3
# An uncached board: page count, the page's users, the first row's rank, unlock tallies and
# the published achievement counts of their games.
BOARD_QUERIES = 5


def _user(username, hardcore_points=0, softcore_points=0, is_active=True):
    return User.objects.create_user(
        username=username,
        password=PASSWORD,
        hardcore_points=hardcore_points,
        softcore_points=softcore_points,
        is_active=is_active,
    )


def _achievement(game, title, status=Achievement.STATUS_COMMUNITY):
    return Achievement.objects.create(
        game=game,
        author=User.objects.get(username=SYSTEM_ACCOUNT),
        title=title,
        description=f"{title} description",
        points=5,
        mem_addr="0xH0001=1",
        status=status,
    )


def _unlock(user, achievement, hardcore):
    """Records an unlock as `handle_awardachievement` does: hardcore writes the softcore twin."""
    unlocked_at = timezone.now()
    UserUnlock.objects.create(
        user=user, achievement=achievement, hardcore=False, unlocked_at=unlocked_at
    )
    if hardcore:
        UserUnlock.objects.create(
            user=user, achievement=achievement, hardcore=True, unlocked_at=unlocked_at
        )


def _get(client, language="en", **params):
    return client.get(RANKING, params, HTTP_ACCEPT_LANGUAGE=language)


def _body(client, **params):
    response = _get(client, **params)
    assert response.status_code == HTTPStatus.OK
    return response.content.decode()


def _rows(body):
    """`(rank, username, rest of the row)` of each board row, in order."""
    rows_start = body.index('id="ranking-rows"')
    return ROW.findall(body, rows_start, body.index("</ol>", rows_start))


def _ranking(body):
    return [(int(rank), username) for rank, username, _rest in _rows(body)]


def _row_of(body, username):
    """The rest of `username`'s row after the profile link, whitespace collapsed."""
    return next(" ".join(rest.split()) for _rank, name, rest in _rows(body) if name == username)


def _header(body):
    return body[body.index("<header") : body.index("</header>")]


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def crash(db):
    _user(SYSTEM_ACCOUNT, is_active=False)
    console = Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


# --- Ordering and who is ranked ---


@pytest.mark.django_db
def test_ranks_by_hardcore_points_by_default(client):
    _user("middle", hardcore_points=50, softcore_points=500)
    _user("top", hardcore_points=90, softcore_points=90)
    _user("bottom", hardcore_points=10, softcore_points=900)
    assert _ranking(_body(client)) == [(1, "top"), (2, "middle"), (3, "bottom")]


@pytest.mark.django_db
def test_softcore_mode_ranks_by_softcore_points(client):
    _user("middle", hardcore_points=50, softcore_points=500)
    _user("top", hardcore_points=90, softcore_points=90)
    _user("softcore-only", softcore_points=900)
    assert _ranking(_body(client, mode="softcore")) == [
        (1, "softcore-only"),
        (2, "middle"),
        (3, "top"),
    ]


@pytest.mark.django_db
def test_leaves_out_inactive_accounts_and_users_without_points_in_the_mode(client, crash):
    _user("ranked", hardcore_points=10, softcore_points=10)
    _user("deactivated", hardcore_points=999, softcore_points=999, is_active=False)
    _user("newcomer")
    _user("softcore-only", softcore_points=40)
    assert _ranking(_body(client)) == [(1, "ranked")]
    assert _ranking(_body(client, mode="softcore")) == [(1, "softcore-only"), (2, "ranked")]


@pytest.mark.django_db
def test_tied_points_share_the_competition_rank(client):
    _user("first", hardcore_points=30)
    _user("tied-b", hardcore_points=20)
    _user("tied-a", hardcore_points=20)
    _user("last", hardcore_points=10)
    assert _ranking(_body(client)) == [(1, "first"), (2, "tied-a"), (2, "tied-b"), (4, "last")]


@pytest.mark.django_db
def test_mode_links_mark_the_active_one_and_swap_the_board_through_htmx(client):
    _user("player", hardcore_points=10, softcore_points=10)
    body = _body(client, mode="softcore")
    assert '<a href="/ranking/?mode=softcore" aria-current="page"' in body
    assert '<a href="/ranking/?mode=hardcore"\n' in body
    assert 'hx-get="/ranking/?mode=hardcore" hx-target="#ranking-board"' in body
    assert 'hx-select="#ranking-board"' in body


@pytest.mark.django_db
def test_empty_ranking_says_so(client):
    _user("newcomer")
    body = _body(client)
    assert _ranking(body) == []
    assert "Nobody has points in this mode yet" in body


# --- Columns ---


@pytest.mark.django_db
def test_row_shows_avatar_profile_link_and_points_of_the_mode(client):
    _user("player", hardcore_points=1_234, softcore_points=5_678)
    hardcore_row = _row_of(_body(client), "player")
    softcore_row = _row_of(_body(client, mode="softcore"), "player")
    assert "1,234 pts" in hardcore_row
    assert "5,678 pts" in softcore_row
    assert f'src="{avatar_path("player")}"' in _body(client)


@pytest.mark.django_db
def test_achievements_count_each_published_one_once_per_mode(client, crash):
    player = _user("player", hardcore_points=10, softcore_points=15)
    hardcore_one, softcore_one, draft = (
        _achievement(crash, "Hardcore one"),
        _achievement(crash, "Softcore one"),
        _achievement(crash, "Draft", status=Achievement.STATUS_DRAFT),
    )
    _unlock(player, hardcore_one, hardcore=True)
    _unlock(player, softcore_one, hardcore=False)
    _unlock(player, draft, hardcore=True)
    assert "1 achievement ·" in _row_of(_body(client), "player")
    assert "2 achievements ·" in _row_of(_body(client, mode="softcore"), "player")


@pytest.mark.django_db
def test_platinums_are_games_with_every_published_achievement_in_hardcore(client, crash):
    other_game = Game.objects.create(title="Crash 2", console=crash.console)
    third_game = Game.objects.create(title="Crash 3", console=crash.console)
    player = _user("player", hardcore_points=30, softcore_points=30)
    for achievement in (_achievement(crash, "Beach"), _achievement(crash, "Jungle")):
        _unlock(player, achievement, hardcore=True)
    _achievement(crash, "Unreleased", status=Achievement.STATUS_DRAFT)
    _unlock(player, _achievement(other_game, "Softcore only"), hardcore=False)
    _unlock(player, _achievement(third_game, "Half"), hardcore=True)
    _achievement(third_game, "Missing")
    for mode in ("hardcore", "softcore"):
        assert "1 platinum</span>" in _row_of(_body(client, mode=mode), "player")


# --- Pages ---


@pytest.mark.django_db
def test_pages_split_the_ranking_and_keep_ranks_across_the_cut(client):
    # Everyone ties at the cut, so page 2 opens with a rank from page 1.
    User.objects.bulk_create(
        User(username=f"player-{index:04d}", hardcore_points=10)
        for index in range(USERS_PER_PAGE + EXTRA_USERS)
    )
    first = _body(client)
    second = _body(client, page=2)
    assert len(_ranking(first)) == USERS_PER_PAGE
    assert _ranking(second) == [(1, "player-0100"), (1, "player-0101")]
    assert "Page 2 of 2" in second
    assert 'href="/ranking/?mode=hardcore&amp;page=1"' in second
    assert 'href="/ranking/?mode=hardcore&amp;page=2"' in first


@pytest.mark.django_db
@pytest.mark.parametrize("page", ["2", "0", "-1", "abc"])
def test_unknown_page_answers_404(client, page):
    _user("player", hardcore_points=10)
    assert _get(client, page=page).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_unknown_mode_answers_400(client):
    assert _get(client, mode="weighted").status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_only_reads_are_allowed(client):
    assert client.post(RANKING).status_code == HTTPStatus.METHOD_NOT_ALLOWED


# --- Cache ---


@pytest.mark.django_db
def test_board_is_cached_per_mode_and_page(client, django_assert_num_queries):
    player = _user("player", hardcore_points=10, softcore_points=10)
    _body(client)
    User.objects.filter(pk=player.pk).update(hardcore_points=0)
    with django_assert_num_queries(0):
        assert _ranking(_body(client)) == [(1, "player")]
    # Another mode is another board, read fresh.
    assert _ranking(_body(client, mode="softcore")) == [(1, "player")]
    cache.clear()
    assert _ranking(_body(client)) == []


@pytest.mark.django_db
def test_board_is_cached_per_language(client):
    _user("player", hardcore_points=10)
    assert "Hardcore points" in _body(client)
    assert "Pontos hardcore" in _get(client, language="pt-br").content.decode()


@pytest.mark.django_db
def test_cached_board_carries_nothing_about_the_viewer_who_filled_it(client):
    _user("player", hardcore_points=10)
    viewer = _user("viewer-without-points")
    client.force_login(viewer)
    assert "viewer-without-points" in _header(_body(client))
    client.logout()
    body = _body(client)
    assert "viewer-without-points" not in body
    assert 'href="/login/"' in _header(body)


# --- Performance ---


def _large_site(console):
    """`LARGE_SITE_USERS` ranked users, `user-<n>` holding n + 1 points; the top
    `UNLOCKING_USERS` hold every achievement of a new game in hardcore."""
    game = Game.objects.create(title="Crash 2", console=console)
    achievements = [
        _achievement(game, f"Achievement {index}") for index in range(LARGE_SITE_ACHIEVEMENTS)
    ]
    users = User.objects.bulk_create(
        User(username=f"user-{index:05d}", hardcore_points=index + 1, softcore_points=index + 1)
        for index in range(LARGE_SITE_USERS)
    )
    UserUnlock.objects.bulk_create(
        UserUnlock(user=user, achievement=achievement, hardcore=hardcore)
        for user in users[-UNLOCKING_USERS:]
        for achievement in achievements
        for hardcore in (False, True)
    )


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["hardcore", "softcore"])
def test_uncached_board_takes_the_same_queries_on_a_small_and_a_large_site(
    client, crash, django_assert_num_queries, mode
):
    lonely = _user("lonely", hardcore_points=1, softcore_points=1)
    _unlock(lonely, _achievement(crash, "First steps"), hardcore=True)
    with django_assert_num_queries(BOARD_QUERIES):
        _body(client, mode=mode)
    cache.clear()
    _large_site(crash.console)
    with django_assert_num_queries(BOARD_QUERIES):
        first_page = _body(client, mode=mode)
    with django_assert_num_queries(BOARD_QUERIES):
        _body(client, mode=mode, page=2)
    top = f"user-{LARGE_SITE_USERS - 1:05d}"
    assert _ranking(first_page)[0] == (1, top)
    assert f"{LARGE_SITE_ACHIEVEMENTS} achievements ·" in _row_of(first_page, top)
    assert "1 platinum</span>" in _row_of(first_page, top)


# --- Navigation ---


@pytest.mark.django_db
def test_nav_links_to_the_ranking(client):
    body = client.get("/", HTTP_ACCEPT_LANGUAGE="en").content.decode()
    assert f'href="{RANKING}"' in _header(body)
    assert client.get(RANKING).status_code == HTTPStatus.OK
