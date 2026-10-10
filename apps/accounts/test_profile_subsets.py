"""The profile over a game with subsets: the platinum counts the core set only, each subset
completed earns its own seal, the subsets the player started show inside their game, and points
come from every set."""

import re
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.achievements.models import Achievement, UserUnlock
from apps.achievements.scoring import recalculate_unlocker_points
from apps.games.models import (
    SET_TYPE_BONUS,
    SET_TYPE_CHALLENGE,
    SET_TYPE_EXCLUSIVE,
    Console,
    Game,
    PlayerGame,
)

User = get_user_model()

PLAYSTATION_RA_ID = 12
CORE_POINTS = 10
BONUS_POINTS = 25
SUBSET_SEAL_TONE = "brand2"


def _achievement(game, author, title, points):
    return Achievement.objects.create(
        game=game,
        author=author,
        title=title,
        description=title,
        points=points,
        mem_addr="0xH0001=1",
        status=Achievement.STATUS_OFFICIAL,
    )


def _unlock(user, achievement, hardcore):
    """Records an unlock as `handle_awardachievement` does: hardcore writes the softcore twin."""
    modes = (False, True) if hardcore else (False,)
    for mode in modes:
        UserUnlock.objects.create(
            user=user, achievement=achievement, hardcore=mode, unlocked_at=timezone.now()
        )


def _subset(core, set_type, set_title):
    return Game.objects.create(
        title=f"{core.title} [Subset - {set_title}]",
        console=core.console,
        parent_game=core,
        set_type=set_type,
        set_title=set_title,
    )


class Crash:
    """Crash with one achievement in its core set, its bonus and its challenge subset."""

    def __init__(self, author):
        console = Console.objects.create(
            ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1"
        )
        self.core = Game.objects.create(title="Crash Bandicoot", console=console)
        self.bonus = _subset(self.core, SET_TYPE_BONUS, "Bonus")
        self.challenge = _subset(self.core, SET_TYPE_CHALLENGE, "Deathless")
        self.core_one = _achievement(self.core, author, "Core one", CORE_POINTS)
        self.bonus_one = _achievement(self.bonus, author, "Bonus one", BONUS_POINTS)
        self.challenge_one = _achievement(self.challenge, author, "Deathless one", BONUS_POINTS)


@pytest.fixture
def player(db):
    return User.objects.create_user(username="teste", password="pw-secret-123")


@pytest.fixture
def crash(player):
    crash = Crash(User.objects.create_user(username="ra-import", is_active=False))
    PlayerGame.objects.create(user=player, game=crash.core)
    return crash


def _profile(client, path="/users/teste/", language="en"):
    response = client.get(path, HTTP_ACCEPT_LANGUAGE=language)
    assert response.status_code == HTTPStatus.OK
    return response


@pytest.mark.django_db
def test_a_completed_subset_is_no_platinum(client, crash, player):
    _unlock(player, crash.bonus_one, hardcore=True)

    context = _profile(client).context

    assert context["platinums"] == 0
    assert context["subsets_completed"] == 1


@pytest.mark.django_db
def test_the_platinum_needs_only_the_core_set(client, crash, player):
    _unlock(player, crash.core_one, hardcore=True)

    context = _profile(client).context

    assert context["platinums"] == 1
    assert context["subsets_completed"] == 0


@pytest.mark.django_db
def test_a_subset_completed_in_softcore_earns_no_seal(client, crash, player):
    _unlock(player, crash.bonus_one, hardcore=False)

    assert _profile(client).context["subsets_completed"] == 0


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/users/teste/", "/users/teste/panel/awards/"])
def test_awards_list_subset_seals_after_platinums(client, crash, player, path):
    _unlock(player, crash.core_one, hardcore=True)
    _unlock(player, crash.bonus_one, hardcore=True)

    body = _profile(client, path).content.decode()

    tones = re.findall(r'class="text-(state-platinum|brand2) rp-hatch', body)
    assert tones == ["state-platinum", SUBSET_SEAL_TONE]
    assert f'href="/games/{crash.core.pk}/#set-{crash.bonus.pk}"' in body
    assert 'title="Crash Bandicoot — Bonus subset · Completed"' in body


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path", ["/users/teste/", "/users/teste/panel/games/", "/users/teste/panel/progress/"]
)
def test_games_played_lists_the_started_subsets_inside_their_game(client, crash, player, path):
    _unlock(player, crash.bonus_one, hardcore=True)

    body = _profile(client, path).content.decode()

    assert ">Bonus subset</span>" in body
    assert "Deathless subset" not in body
    started = body[body.index(">Bonus subset</span>") :]
    assert "<span>1/1</span>" in started
    assert ">Completed</span>" in started


@pytest.mark.django_db
def test_subsets_stay_inside_their_game_not_listed_as_games(client, crash, player):
    _unlock(player, crash.bonus_one, hardcore=False)
    PlayerGame.objects.create(user=player, game=crash.bonus)

    context = _profile(client).context

    assert [game["game"] for game in context["completion"]] == [crash.core]
    assert context["games_played"] == 1


@pytest.mark.django_db
def test_a_player_of_an_exclusive_disc_alone_sees_its_seal_inside_the_core_game(client, crash):
    """An exclusive disc's sessions are recorded on its subset, never on the core game."""
    exclusive = _subset(crash.core, SET_TYPE_EXCLUSIVE, "Prototype")
    exclusive_one = _achievement(exclusive, crash.core_one.author, "Prototype one", BONUS_POINTS)
    disc_player = User.objects.create_user(username="disco", password="pw-secret-123")
    PlayerGame.objects.create(user=disc_player, game=exclusive)
    _unlock(disc_player, exclusive_one, hardcore=True)

    response = _profile(client, "/users/disco/")
    context = response.context

    assert [game["game"] for game in context["completion"]] == [crash.core]
    assert context["games_played"] == 1
    assert context["platinums"] == 0
    assert context["subsets_completed"] == 1
    assert ">Prototype subset</span>" in response.content.decode()


@pytest.mark.django_db
def test_the_statistics_count_subsets_completed(client, crash, player):
    _unlock(player, crash.bonus_one, hardcore=True)
    _unlock(player, crash.challenge_one, hardcore=True)

    english = _profile(client).content.decode()
    portuguese = _profile(client, language="pt-br").content.decode()

    assert re.search(r"Subsets completed</div>\s*</div>\s*<span[^>]*>2</span>", english)
    assert "Subsets concluídos" in portuguese
    assert "sets principais" in portuguese


@pytest.mark.django_db
def test_points_count_every_set(client, crash, player):
    _unlock(player, crash.core_one, hardcore=True)
    _unlock(player, crash.bonus_one, hardcore=False)
    with transaction.atomic():
        recalculate_unlocker_points([crash.core_one.pk, crash.bonus_one.pk])

    points = _profile(client).context["points"]

    assert points.hardcore == CORE_POINTS
    assert points.softcore == CORE_POINTS + BONUS_POINTS


@pytest.mark.django_db
def test_profile_queries_do_not_grow_with_subsets(client, crash, player):
    def queries():
        with CaptureQueriesContext(connection) as captured:
            _profile(client)
        return len(captured)

    _unlock(player, crash.bonus_one, hardcore=True)
    baseline = queries()
    _unlock(player, crash.challenge_one, hardcore=True)
    more = _subset(crash.core, SET_TYPE_BONUS, "More")
    _unlock(player, _achievement(more, player, "More one", BONUS_POINTS), hardcore=True)

    assert queries() == baseline
