"""The achievement page: its badge, fields, status chip and unlock counts over real unlocks, an
unofficial achievement reaching everyone."""

from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.achievements.models import Achievement, UserUnlock
from apps.core import stats
from apps.games.models import Console, Game, PlayerGame
from apps.images.catalog import badge_path

User = get_user_model()

PLAYSTATION_RA_ID = 12
PASSWORD = "pw-secret-123"
UNKNOWN_ID = 999_999
POINTS = 25


def _user(username, is_staff=False, is_active=True):
    return User.objects.create_user(
        username=username, password=PASSWORD, is_staff=is_staff, is_active=is_active
    )


@pytest.fixture
def author(db):
    return _user("author")


@pytest.fixture
def other(db):
    return _user("other")


@pytest.fixture
def game(db):
    console = Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


def _achievement(game, author, status=Achievement.STATUS_OFFICIAL):
    return Achievement.objects.create(
        game=game,
        author=author,
        title="Hog Wild",
        description="Ride the hog\nwithout a hit",
        points=POINTS,
        type=Achievement.TYPE_PROGRESSION,
        mem_addr="0xH0001=1",
        status=status,
    )


def _unlock(user, achievement, hardcore):
    """Records an unlock as `handle_awardachievement` does: hardcore writes the softcore twin."""
    unlocked_at = timezone.now()
    modes = (False, True) if hardcore else (False,)
    for mode in modes:
        UserUnlock.objects.create(
            user=user, achievement=achievement, hardcore=mode, unlocked_at=unlocked_at
        )


def _url(achievement, game_id=None):
    return f"/games/{game_id or achievement.game_id}/achievements/{achievement.pk}/"


def _get(client, url):
    return client.get(url, HTTP_ACCEPT_LANGUAGE="en")


def _page(client, achievement):
    response = _get(client, _url(achievement))
    assert response.status_code == HTTPStatus.OK
    return response.content.decode()


def _stat(body, label):
    """The value of the stat line labelled `label`."""
    start = body.index(f">{label}</div>")
    value_start = body.index('<span class="font-data text-base font-bold text-txt">', start)
    value_start = body.index(">", value_start) + 1
    return body[value_start : body.index("</span>", value_start)]


@pytest.mark.django_db
def test_page_shows_the_achievement(client, author, game):
    achievement = _achievement(game, author)
    body = _page(client, achievement)
    assert "<h1" in body and "Hog Wild" in body
    assert "Ride the hog\nwithout a hit" in body
    assert f"{POINTS} pts" in body
    assert "Progression" in body
    assert "Official" in body
    assert f'href="/users/{author.username}/"' in body
    assert badge_path(achievement.badge_name) in body
    assert f'href="/games/{game.pk}/"' in body
    assert f'href="/games/{game.pk}/achievements/{achievement.pk}/history/"' in body


@pytest.mark.django_db
def test_page_counts_the_unlockers_by_mode_and_the_game_players(client, author, other, game):
    achievement = _achievement(game, author)
    inactive = _user("inactive", is_active=False)
    softcore_player = _user("softcore-player")
    _unlock(other, achievement, hardcore=True)
    _unlock(softcore_player, achievement, hardcore=False)
    _unlock(inactive, achievement, hardcore=True)
    for user in (other, softcore_player, author, inactive):
        PlayerGame.objects.create(user=user, game=game)
    body = _page(client, achievement)
    assert _stat(body, "Players who unlocked it") == "2"
    assert _stat(body, "In hardcore") == "1"
    assert _stat(body, "Players of the game") == "3"


@pytest.mark.django_db
def test_achievement_unlockers_counts_nothing_while_unofficial(author, other, game):
    achievement = _achievement(game, author)
    _unlock(other, achievement, hardcore=True)
    assert stats.achievement_unlockers(achievement) == stats.ByMode(hardcore=1, softcore=1)
    achievement.status = Achievement.STATUS_UNOFFICIAL
    achievement.save()
    assert stats.achievement_unlockers(achievement) == stats.ByMode(hardcore=0, softcore=0)


@pytest.mark.django_db
def test_an_unofficial_page_reaches_everyone_without_unlock_counts(client, author, other, game):
    unofficial = _achievement(game, author, status=Achievement.STATUS_UNOFFICIAL)
    anonymous_body = _page(client, unofficial)
    client.force_login(other)
    for body in (anonymous_body, _page(client, unofficial)):
        assert "Unofficial" in body
        assert "An unofficial achievement is never awarded" in body
        assert "Players who unlocked it" not in body


@pytest.mark.django_db
def test_the_edit_link_shows_only_to_the_author_and_staff(client, author, other, game):
    achievement = _achievement(game, author)
    edit_link = f'href="/games/{game.pk}/achievements/{achievement.pk}/edit/"'
    assert edit_link not in _page(client, achievement)
    client.force_login(other)
    assert edit_link not in _page(client, achievement)
    client.force_login(author)
    assert edit_link in _page(client, achievement)
    client.force_login(_user("staff", is_staff=True))
    assert edit_link in _page(client, achievement)


@pytest.mark.django_db
def test_page_escapes_the_achievement_text(client, author, game):
    achievement = _achievement(game, author)
    achievement.title = "<b>Bold</b>"
    achievement.save()
    body = _page(client, achievement)
    assert "<b>Bold</b>" not in body
    assert "&lt;b&gt;Bold&lt;/b&gt;" in body


@pytest.mark.django_db
def test_an_unknown_achievement_or_one_of_another_game_is_404(client, author, game):
    achievement = _achievement(game, author)
    other_game = Game.objects.create(title="Spyro", console=game.console)
    assert _get(client, _url(achievement, game_id=other_game.pk)).status_code == (
        HTTPStatus.NOT_FOUND
    )
    unknown = f"/games/{game.pk}/achievements/{UNKNOWN_ID}/"
    assert _get(client, unknown).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_page_rejects_post(client, author, game):
    achievement = _achievement(game, author)
    client.force_login(author)
    assert client.post(_url(achievement)).status_code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_the_game_page_links_each_achievement_to_its_page(client, author, game):
    achievement = _achievement(game, author)
    response = _get(client, f"/games/{game.pk}/")
    assert f'href="/games/{game.pk}/achievements/{achievement.pk}/"' in response.content.decode()
