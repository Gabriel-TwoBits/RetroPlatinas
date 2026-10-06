"""The feed page and the list fragment it polls."""

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.achievements.models import Achievement, UserUnlock
from apps.core.feed import FEED_UNLOCKS_SHOWN, POLL_SECONDS
from apps.games.models import Console, Game
from apps.images.catalog import avatar_path, badge_path

User = get_user_model()

PLAYSTATION_RA_ID = 12
NINTENDO_64_RA_ID = 2
SYSTEM_ACCOUNT = "ra-import"
PASSWORD = "pw-secret-123"
# More rows than the feed lists, so the cut is visible.
EXTRA_ROWS = 3
FEED_PATH = "/feed/"
FEED_LIST_PATH = "/feed/list/"
PATHS = [FEED_PATH, FEED_LIST_PATH]
# The desktop nav, the mobile nav and the footer.
FEED_LINKS_PER_PAGE = 3


def _user(username, is_active=True):
    return User.objects.create_user(username=username, password=PASSWORD, is_active=is_active)


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


def _unlock(user, achievement, hardcore, unlocked_at=None):
    """Records an unlock as `handle_awardachievement` does: hardcore writes the softcore twin."""
    unlocked_at = unlocked_at or timezone.now()
    UserUnlock.objects.get_or_create(
        user=user, achievement=achievement, hardcore=False, defaults={"unlocked_at": unlocked_at}
    )
    if hardcore:
        UserUnlock.objects.create(
            user=user, achievement=achievement, hardcore=True, unlocked_at=unlocked_at
        )


def _get(client, path, language="en"):
    return client.get(path, HTTP_ACCEPT_LANGUAGE=language)


def _shown(resp):
    return [(row["unlock"].achievement, row["unlock"].hardcore) for row in resp.context["rows"]]


@pytest.fixture
def crash(db):
    _user(SYSTEM_ACCOUNT, is_active=False)
    playstation = Console.objects.create(
        ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1"
    )
    return Game.objects.create(title="Crash Bandicoot", console=playstation)


@pytest.fixture
def player(db):
    return _user("teste")


# --- Rows ---


@pytest.mark.django_db
@pytest.mark.parametrize("path", PATHS)
def test_feed_lists_unlocks_newest_first_once_each(client, crash, player, path):
    now = timezone.now()
    beach = _achievement(crash, "N. Sanity Beach")
    rollers = _achievement(crash, "Jungle Rollers")
    _unlock(player, beach, hardcore=True, unlocked_at=now - timedelta(hours=2))
    _unlock(player, rollers, hardcore=False, unlocked_at=now - timedelta(minutes=3))

    resp = _get(client, path)

    assert resp.status_code == HTTPStatus.OK
    assert _shown(resp) == [(rollers, False), (beach, True)]
    body = resp.content.decode()
    assert body.index("Jungle Rollers") < body.index("N. Sanity Beach")
    assert body.count('href="/users/teste/"') == len(resp.context["rows"])
    assert body.count(f'href="/games/{crash.pk}/"') == len(resp.context["rows"])
    assert f'src="{avatar_path(player.username)}"' in body
    assert f'src="{badge_path(beach.badge_name)}"' in body
    assert "3\xa0minutes ago" in body
    assert "2\xa0hours ago" in body
    assert body.count(">hardcore<") == 1


@pytest.mark.django_db
def test_feed_shows_a_hardcore_upgrade_of_an_earlier_softcore_unlock_apart(client, crash, player):
    beach = _achievement(crash, "N. Sanity Beach")
    _unlock(player, beach, hardcore=False, unlocked_at=timezone.now() - timedelta(days=1))
    _unlock(player, beach, hardcore=True)

    assert _shown(_get(client, FEED_PATH)) == [(beach, True), (beach, False)]


@pytest.mark.django_db
@pytest.mark.parametrize("path", PATHS)
def test_feed_leaves_out_drafts_and_inactive_users(client, crash, player, path):
    draft = _achievement(crash, "Secret draft", status=Achievement.STATUS_DRAFT)
    beach = _achievement(crash, "N. Sanity Beach")
    _unlock(player, draft, hardcore=False)
    _unlock(_user("banned", is_active=False), beach, hardcore=True)

    resp = _get(client, path)

    assert resp.context["rows"] == []
    body = resp.content.decode()
    assert "Secret draft" not in body
    assert "banned" not in body


@pytest.mark.django_db
def test_feed_shows_only_the_latest_unlocks(client, crash, player):
    now = timezone.now()
    achievements = [
        _achievement(crash, f"Achievement {index}")
        for index in range(FEED_UNLOCKS_SHOWN + EXTRA_ROWS)
    ]
    for minutes_ago, achievement in enumerate(achievements):
        _unlock(
            player, achievement, hardcore=False, unlocked_at=now - timedelta(minutes=minutes_ago)
        )

    rows = _get(client, FEED_PATH).context["rows"]

    assert [row["unlock"].achievement for row in rows] == achievements[:FEED_UNLOCKS_SHOWN]


@pytest.mark.django_db
@pytest.mark.parametrize("path", PATHS)
def test_empty_feed_shows_an_honest_empty_state_linking_the_guide(client, crash, path):
    body = _get(client, path).content.decode()

    assert "No unlocks yet" in body
    assert 'href="/docs/getting-started/"' in body


# --- Polling ---


@pytest.mark.django_db
def test_feed_polls_the_list_fragment(client, crash):
    body = _get(client, FEED_PATH).content.decode()

    assert f'hx-get="{FEED_LIST_PATH}"' in body
    assert f'hx-trigger="every {POLL_SECONDS}s"' in body
    assert f"refreshed every {POLL_SECONDS} seconds" in body


@pytest.mark.django_db
def test_list_fragment_is_the_bare_list_with_unlocks_made_since_the_page_loaded(
    client, crash, player
):
    _get(client, FEED_PATH)
    beach = _achievement(crash, "N. Sanity Beach")
    _unlock(player, beach, hardcore=False)

    resp = _get(client, FEED_LIST_PATH)

    body = resp.content.decode()
    assert body.lstrip().startswith('<ol id="feed-list">')
    assert "<html" not in body
    assert "hx-trigger" not in body
    assert "N. Sanity Beach" in body


@pytest.mark.django_db
@pytest.mark.parametrize("path", PATHS)
def test_feed_rejects_writes(client, crash, path):
    assert client.post(path).status_code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.django_db
@pytest.mark.parametrize("path", PATHS)
def test_feed_queries_do_not_grow_with_rows(client, crash, path):
    def query_count():
        with CaptureQueriesContext(connection) as queries:
            _get(client, path)
        return len(queries)

    beach = _achievement(crash, "N. Sanity Beach")
    _unlock(_user("first"), beach, hardcore=True)
    baseline = query_count()

    nintendo_64 = Console.objects.create(
        ra_id=NINTENDO_64_RA_ID, name="Nintendo 64", short_name="N64"
    )
    for index in range(EXTRA_ROWS):
        game = Game.objects.create(title=f"Game {index}", console=nintendo_64)
        _unlock(_user(f"other{index}"), _achievement(game, f"Achievement {index}"), hardcore=True)

    assert query_count() == baseline


# --- Filter ---


@pytest.mark.django_db
def test_feed_shows_all_active_and_friends_disabled_with_a_note(client, crash):
    body = _get(client, FEED_PATH).content.decode()

    assert f'<a href="{FEED_PATH}" aria-current="page"' in body
    start = body.index('aria-disabled="true"')
    friends = body[start : body.index("</nav>", start)]
    assert "Friends" in friends
    assert "href" not in friends
    assert "The Friends filter arrives once you can follow other players." in body


# --- Navigation and language ---


@pytest.mark.django_db
def test_nav_and_footer_link_the_feed(client, crash):
    resp = _get(client, "/")

    assert resp.status_code == HTTPStatus.OK
    assert resp.content.decode().count(f'href="{FEED_PATH}"') == FEED_LINKS_PER_PAGE


@pytest.mark.django_db
@pytest.mark.parametrize("path", PATHS)
def test_feed_is_translated_to_brazilian_portuguese(client, crash, player, path):
    beach = _achievement(crash, "N. Sanity Beach")
    _unlock(player, beach, hardcore=True, unlocked_at=timezone.now() - timedelta(minutes=3))

    body = _get(client, path, "pt-br").content.decode()

    assert "desbloqueou" in body
    assert " em <a" in body
    assert "3\xa0minutos atrás" in body


@pytest.mark.django_db
def test_feed_page_is_translated_to_brazilian_portuguese(client, crash):
    body = _get(client, FEED_PATH, "pt-br").content.decode()

    assert "Todos" in body
    assert "Amigos" in body
    assert "Nenhum desbloqueio ainda" in body
    assert f"atualizados a cada {POLL_SECONDS} segundos" in body
