"""Achievements and leaderboards of a subset, wherever the site lists them outside the game page,
carry the subset's chip and link to its section of the core game's page; the home page counts each
game's subsets."""

import re
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.achievements.models import Achievement, UserUnlock
from apps.games.models import SET_TYPE_BONUS, SET_TYPE_EXCLUSIVE, Console, Game
from apps.leaderboards.models import Leaderboard

User = get_user_model()

PLAYSTATION_RA_ID = 12
POINTS = 10
CORE_TITLE = "Crash Bandicoot"
SUBSET_GAME_TITLE = "Crash Bandicoot [Subset - Bonus]"
CHIP = ">Bonus subset</span>"
CORE_PLAYERS = 2


def _achievement(game, author, title):
    return Achievement.objects.create(
        game=game,
        author=author,
        title=title,
        description=f"{title} description",
        points=POINTS,
        mem_addr="0xH0001=1",
        status=Achievement.STATUS_OFFICIAL,
    )


@pytest.fixture
def player(db):
    user = User.objects.create_user(username="player", password="pw-secret-123")
    user.softcore_points = POINTS
    user.save(update_fields=["softcore_points"])
    return user


@pytest.fixture
def core(db):
    console = Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")
    return Game.objects.create(title=CORE_TITLE, console=console)


@pytest.fixture
def bonus(core):
    return Game.objects.create(
        title=SUBSET_GAME_TITLE,
        console=core.console,
        parent_game=core,
        set_type=SET_TYPE_BONUS,
        set_title="Bonus",
    )


@pytest.fixture
def bonus_one(bonus, player):
    return _achievement(bonus, player, "Bonus one")


@pytest.fixture
def unlocked(player, bonus_one):
    UserUnlock.objects.create(
        user=player, achievement=bonus_one, hardcore=False, unlocked_at=timezone.now()
    )


def _get(client, path, language="en"):
    response = client.get(path, HTTP_ACCEPT_LANGUAGE=language)
    assert response.status_code == HTTPStatus.OK
    return response.content.decode()


def _assert_names_the_subset(body, core, bonus):
    assert f'href="/games/{core.pk}/#set-{bonus.pk}"' in body
    assert re.search(rf">(← )?{CORE_TITLE}</a>\s*<span", body)
    assert CHIP in body
    assert SUBSET_GAME_TITLE not in body


@pytest.mark.django_db
@pytest.mark.parametrize("page", ["detail", "history"])
def test_a_subset_achievements_pages_name_the_subset(client, core, bonus, bonus_one, page):
    path = f"/games/{bonus.pk}/achievements/{bonus_one.pk}/"
    if page == "history":
        path += "history/"
    else:
        # The achievement page itself.
        pass
    _assert_names_the_subset(_get(client, path), core, bonus)


@pytest.mark.django_db
def test_a_core_achievements_page_has_no_subset_chip(client, core, player):
    core_one = _achievement(core, player, "Core one")
    body = _get(client, f"/games/{core.pk}/achievements/{core_one.pk}/")
    assert f'href="/games/{core.pk}/"' in body
    assert "subset</span>" not in body


@pytest.mark.django_db
def test_a_subset_achievement_counts_the_core_games_players(client, core, bonus, bonus_one):
    for index in range(CORE_PLAYERS):
        user = User.objects.create_user(username=f"core-player-{index}")
        core.players.create(user=user)
    body = _get(client, f"/games/{bonus.pk}/achievements/{bonus_one.pk}/")
    line = body[body.index("Players of the game") :]
    assert f'text-txt">{CORE_PLAYERS}</span>' in line[: line.index("</span>") + len("</span>")]


@pytest.mark.django_db
def test_an_exclusive_achievement_counts_the_players_of_its_own_disc(client, core, player):
    exclusive = Game.objects.create(
        title="Crash Bandicoot [Subset - Prototype]",
        console=core.console,
        parent_game=core,
        set_type=SET_TYPE_EXCLUSIVE,
        set_title="Prototype",
    )
    exclusive_one = _achievement(exclusive, player, "Prototype one")
    core.players.create(user=User.objects.create_user(username="core-player"))
    exclusive.players.create(user=player)
    body = _get(client, f"/games/{exclusive.pk}/achievements/{exclusive_one.pk}/")
    line = body[body.index("Players of the game") :]
    assert 'text-txt">1</span>' in line[: line.index("</span>") + len("</span>")]


@pytest.mark.django_db
def test_a_subset_leaderboards_page_names_the_subset(client, core, bonus):
    board = Leaderboard.objects.create(game=bonus, title="Bonus board", mem_addr="STA:0=1")
    _assert_names_the_subset(
        _get(client, f"/games/{bonus.pk}/leaderboards/{board.pk}/"), core, bonus
    )


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/feed/", "/feed/list/", "/", "/users/player/"])
def test_unlock_lists_name_the_subset(client, core, bonus, unlocked, path):
    _assert_names_the_subset(_get(client, path), core, bonus)


@pytest.mark.django_db
def test_the_subset_chip_is_translated(client, core, bonus, unlocked):
    assert ">Subset Bonus</span>" in _get(client, "/feed/", language="pt-br")


@pytest.mark.django_db
def test_the_home_set_card_counts_the_games_subsets(client, core, bonus, player):
    _achievement(core, player, "Core one")
    Game.objects.create(
        title="Crash Bandicoot [Subset - Deathless]",
        console=core.console,
        parent_game=core,
        set_type=SET_TYPE_BONUS,
        set_title="Deathless",
    )
    assert "2 subsets" in _get(client, "/")
    assert "2 subsets" in _get(client, "/", language="pt-br")


@pytest.mark.django_db
def test_the_home_set_card_of_a_game_without_subsets_counts_none(client, core, player):
    _achievement(core, player, "Core one")
    body = _get(client, "/")
    card = re.search(rf'<a href="/games/{core.pk}/".*?</a>', body, re.DOTALL)
    assert card, "set card missing"
    assert "subset" not in card.group(0)
