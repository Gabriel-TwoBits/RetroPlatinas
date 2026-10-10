"""The game page built around the core set and its subsets: a section per set with its progress,
seal and unofficial part, the opt-in control, the staff's new subset form, and how the choice
reaches the emulator."""

from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.achievements.models import Achievement, UserUnlock
from apps.api.handlers import API_TOKEN_LIFETIME
from apps.games.models import (
    MD5_HEX_DIGITS,
    SET_TYPE_BONUS,
    SET_TYPE_CHALLENGE,
    SET_TYPE_EXCLUSIVE,
    SET_TYPE_SPECIALTY,
    Console,
    Game,
    GameHash,
    UserSetPreference,
)
from apps.leaderboards.models import Leaderboard

User = get_user_model()

PLAYER = "player"
PLAYER_TOKEN = "player-token"
PASSWORD = "pw-secret-123"
PLAYSTATION_RA_ID = 12
CORE_MD5 = "c" * MD5_HEX_DIGITS
SPECIALTY_MD5 = "5" * MD5_HEX_DIGITS
POINTS = 10
CORE_TITLE = "Crash Bandicoot"


def _user(username, **fields):
    return User.objects.create_user(username=username, password=PASSWORD, **fields)


def _achievement(game, author, title, status=Achievement.STATUS_OFFICIAL):
    return Achievement.objects.create(
        game=game,
        author=author,
        title=title,
        description=f"{title} description",
        points=POINTS,
        mem_addr="0xH0001=1",
        status=status,
    )


def _unlock(user, achievement, hardcore):
    """Records an unlock as `handle_awardachievement` does: hardcore writes the softcore twin."""
    modes = (False, True) if hardcore else (False,)
    for mode in modes:
        UserUnlock.objects.create(
            user=user, achievement=achievement, hardcore=mode, unlocked_at=timezone.now()
        )


class Sets:
    """Crash with one achievement per set: a core hash, then a bonus, a challenge, a specialty
    (with its disc) and an exclusive subset (without one), created out of site order."""

    def __init__(self, author):
        self.console = Console.objects.create(
            ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1"
        )
        self.core = Game.objects.create(title=CORE_TITLE, console=self.console)
        GameHash.objects.create(game=self.core, md5=CORE_MD5, label="NTSC-U")
        self.exclusive = self._subset(SET_TYPE_EXCLUSIVE, "Prototype")
        self.specialty = self._subset(SET_TYPE_SPECIALTY, "Japanese")
        GameHash.objects.create(game=self.specialty, md5=SPECIALTY_MD5, label="NTSC-J")
        self.challenge = self._subset(SET_TYPE_CHALLENGE, "Deathless")
        self.bonus = self._subset(SET_TYPE_BONUS, "Bonus")
        self.core_one = _achievement(self.core, author, "Core one")
        self.bonus_one = _achievement(self.bonus, author, "Bonus one")
        self.challenge_one = _achievement(self.challenge, author, "Deathless one")

    def _subset(self, set_type, set_title):
        return Game.objects.create(
            title=f"{CORE_TITLE} [Subset - {set_title}]",
            console=self.console,
            parent_game=self.core,
            set_type=set_type,
            set_title=set_title,
        )


@pytest.fixture
def author(db):
    return _user("ra-import", is_active=False)


@pytest.fixture
def sets(author):
    return Sets(author)


@pytest.fixture
def player(db):
    user = _user(PLAYER)
    user.api_token = PLAYER_TOKEN
    user.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    user.save(update_fields=["api_token", "api_token_expires_at"])
    return user


@pytest.fixture
def staff(db):
    return _user("staff", is_staff=True)


def _page(client, game, language="en"):
    response = client.get(f"/games/{game.pk}/", HTTP_ACCEPT_LANGUAGE=language)
    assert response.status_code == HTTPStatus.OK
    return response.content.decode()


def _section(body, game):
    """The markup of the set's section on the page."""
    start = body.index(f'<section id="set-{game.pk}"')
    return body[start : body.index("</section>", start)]


def _play(client, subset, play, **headers):
    return client.post(
        f"/games/{subset.pk}/play/", {"play": play}, HTTP_ACCEPT_LANGUAGE="en", **headers
    )


def _served_set_ids(client):
    data = client.post(
        "/dorequest.php", {"r": "achievementsets", "u": PLAYER, "t": PLAYER_TOKEN, "m": CORE_MD5}
    ).json()
    return [served["AchievementSetId"] for served in data["Sets"]]


# --- Sections ---


@pytest.mark.django_db
def test_the_core_set_comes_first_then_each_subset_by_type(client, sets):
    body = _page(client, sets.core)
    order = [sets.core, sets.bonus, sets.challenge, sets.specialty, sets.exclusive]
    positions = [body.index(f'<section id="set-{game.pk}"') for game in order]
    assert positions == sorted(positions)
    assert ">Core set\n" in _section(body, sets.core)
    assert ">Bonus\n" in _section(body, sets.bonus)
    assert 'bg-brand2"></span>Deathless' in _section(body, sets.challenge)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("subset", "explanation"),
    [
        ("bonus", "challenges you can take on while playing the game normally"),
        ("challenge", "a specific challenge run"),
        ("specialty", "needs a different disc or version of the game, and plays alongside"),
        ("exclusive", "needs a different disc or version of the game, and plays on its own"),
    ],
)
def test_each_subset_explains_its_type(client, sets, subset, explanation):
    assert explanation in _section(_page(client, sets.core), getattr(sets, subset))


@pytest.mark.django_db
def test_each_set_lists_its_own_achievements(client, sets):
    body = _page(client, sets.core)
    assert ">Core one<" in _section(body, sets.core)
    assert ">Bonus one<" in _section(body, sets.bonus)
    assert ">Bonus one<" not in _section(body, sets.core)
    assert f'href="/games/{sets.bonus.pk}/achievements/{sets.bonus_one.pk}/"' in body
    assert "No achievements yet" in _section(body, sets.exclusive)


@pytest.mark.django_db
def test_the_header_totals_count_the_core_set(client, sets):
    body = _page(client, sets.core)
    header = body[: body.index('id="game-tabs"')]
    assert 'text-txt">1</div>' in header
    assert f'text-gold">{POINTS}</div>' in header


@pytest.mark.django_db
def test_each_set_keeps_its_unofficial_achievements_collapsed(client, sets, author):
    _achievement(sets.bonus, author, "Bonus draft", status=Achievement.STATUS_UNOFFICIAL)
    body = _page(client, sets.core)
    bonus = _section(body, sets.bonus)
    assert bonus.index(f'<details id="unofficial-{sets.bonus.pk}"') < bonus.index(">Bonus draft<")
    assert "<details" not in _section(body, sets.core)


@pytest.mark.django_db
def test_a_subset_has_no_page_of_its_own(client, sets):
    response = client.get(f"/games/{sets.bonus.pk}/")
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == f"/games/{sets.core.pk}/#set-{sets.bonus.pk}"
    panel = client.get(f"/games/{sets.bonus.pk}/panel/achievements/")
    assert panel.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_the_filter_applies_to_every_set(client, sets, player):
    _unlock(player, sets.bonus_one, hardcore=False)
    client.force_login(player)
    response = client.get(
        f"/games/{sets.core.pk}/panel/achievements/",
        {"filter": "unlocked"},
        HTTP_ACCEPT_LANGUAGE="en",
    )
    body = response.content.decode()
    assert ">Bonus one<" in _section(body, sets.bonus)
    assert ">Core one<" not in body
    assert "No achievements unlocked yet" in _section(body, sets.core)


@pytest.mark.django_db
def test_the_page_queries_do_not_grow_with_subsets(client, sets, player, author):
    client.force_login(player)

    def queries():
        with CaptureQueriesContext(connection) as captured:
            _page(client, sets.core)
        return len(captured)

    baseline = queries()
    for set_type, set_title in [(SET_TYPE_BONUS, "More"), (SET_TYPE_SPECIALTY, "PAL")]:
        subset = sets._subset(set_type, set_title)
        _unlock(player, _achievement(subset, author, f"{set_title} one"), hardcore=True)
    assert queries() == baseline


# --- Progress and seals ---


@pytest.mark.django_db
def test_an_anonymous_visitor_sees_no_progress(client, sets):
    body = _page(client, sets.core)
    assert "unlocked (" not in body


@pytest.mark.django_db
def test_each_set_shows_the_viewers_progress(client, sets, player, author):
    _achievement(sets.core, author, "Core two")
    _unlock(player, sets.core_one, hardcore=True)
    client.force_login(player)
    body = _page(client, sets.core)
    assert "1/2 unlocked (1 hardcore) · 50%" in _section(body, sets.core)
    assert "0/1 unlocked (0 hardcore) · 0%" in _section(body, sets.bonus)


@pytest.mark.django_db
def test_every_core_achievement_in_hardcore_earns_the_platinum(client, sets, player):
    _unlock(player, sets.core_one, hardcore=True)
    client.force_login(player)
    core = _section(_page(client, sets.core), sets.core)
    assert 'text-state-platinum">Platinum</span>' in core
    assert "bg-state-platinum" in core


@pytest.mark.django_db
def test_softcore_unlocks_earn_no_seal(client, sets, player):
    _unlock(player, sets.core_one, hardcore=False)
    _unlock(player, sets.bonus_one, hardcore=False)
    client.force_login(player)
    body = _page(client, sets.core)
    assert "Platinum</span>" not in body
    assert "Completed</span>" not in body


@pytest.mark.django_db
def test_a_subset_completed_in_hardcore_earns_its_own_seal(client, sets, player):
    _unlock(player, sets.bonus_one, hardcore=True)
    client.force_login(player)
    body = _page(client, sets.core)
    assert 'text-brand2">Completed</span>' in _section(body, sets.bonus)
    assert "Platinum</span>" not in _section(body, sets.core)
    assert "Completed</span>" not in _section(body, sets.challenge)


@pytest.mark.django_db
def test_seals_are_translated(client, sets, player):
    _unlock(player, sets.core_one, hardcore=True)
    _unlock(player, sets.bonus_one, hardcore=True)
    client.force_login(player)
    body = _page(client, sets.core, language="pt-br")
    assert ">Set principal\n" in body
    assert ">Platinado</span>" in body
    assert ">Concluído</span>" in body


# --- Opt-in control ---


@pytest.mark.django_db
def test_an_anonymous_visitor_is_offered_to_log_in_to_play_a_subset(client, sets):
    bonus = _section(_page(client, sets.core), sets.bonus)
    assert "Log in to play this subset" in bonus
    assert f"/login/?next=/games/{sets.core.pk}/%23set-{sets.bonus.pk}" in bonus
    assert 'role="switch"' not in bonus


@pytest.mark.django_db
def test_every_subset_starts_off(client, sets, player):
    client.force_login(player)
    body = _page(client, sets.core)
    for subset in (sets.bonus, sets.challenge):
        section = _section(body, subset)
        assert 'role="switch" aria-checked="false"' in section
        assert 'name="play" value="on"' in section
        assert "applies the next time you open the game in the emulator" in section
    assert 'role="switch"' not in _section(body, sets.core)


@pytest.mark.django_db
def test_a_specialty_or_exclusive_subset_names_its_disc_instead_of_a_toggle(client, sets, player):
    client.force_login(player)
    body = _page(client, sets.core)
    specialty = _section(body, sets.specialty)
    assert SPECIALTY_MD5 in specialty and "NTSC-J" in specialty
    assert 'role="switch"' not in specialty
    exclusive = _section(body, sets.exclusive)
    assert "No disc is linked to this subset yet." in exclusive
    assert 'role="switch"' not in exclusive


@pytest.mark.django_db
def test_opting_in_swaps_the_control_and_serves_the_subset(client, sets, player):
    client.force_login(player)
    assert _served_set_ids(client) == [sets.core.pk]

    response = _play(client, sets.bonus, "on", HTTP_HX_REQUEST="true")

    assert response.status_code == HTTPStatus.OK
    body = response.content.decode()
    assert f'<div id="opt-in-{sets.bonus.pk}"' in body and "<!DOCTYPE" not in body
    assert 'aria-checked="true"' in body and 'name="play" value="off"' in body
    assert UserSetPreference.objects.get(user=player, subset_game=sets.bonus).opted_in
    assert _served_set_ids(client) == [sets.core.pk, sets.bonus.pk]
    assert 'aria-checked="true"' in _section(_page(client, sets.core), sets.bonus)


@pytest.mark.django_db
def test_opting_out_stops_serving_the_subset(client, sets, player):
    client.force_login(player)
    _play(client, sets.bonus, "on", HTTP_HX_REQUEST="true")
    _play(client, sets.challenge, "on", HTTP_HX_REQUEST="true")

    response = _play(client, sets.bonus, "off", HTTP_HX_REQUEST="true")

    assert 'aria-checked="false"' in response.content.decode()
    assert UserSetPreference.objects.filter(user=player).count() == len(
        [sets.bonus, sets.challenge]
    )
    assert _served_set_ids(client) == [sets.core.pk, sets.challenge.pk]


@pytest.mark.django_db
def test_a_plain_opt_in_post_returns_to_the_subsets_section(client, sets, player):
    client.force_login(player)
    response = _play(client, sets.challenge, "on")
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == f"/games/{sets.core.pk}/#set-{sets.challenge.pk}"


@pytest.mark.django_db
def test_opting_in_needs_a_session(client, sets):
    page = f"http://testserver/games/{sets.core.pk}/"
    htmx = _play(client, sets.bonus, "on", HTTP_HX_REQUEST="true", HTTP_HX_CURRENT_URL=page)
    assert htmx["HX-Redirect"] == (f"/login/?next=/games/{sets.core.pk}/%23set-{sets.bonus.pk}")
    plain = _play(client, sets.bonus, "on")
    assert plain.status_code == HTTPStatus.FOUND
    assert plain["Location"].startswith("/login/")
    assert not UserSetPreference.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("play", ["", "yes", "1"])
def test_opting_in_needs_on_or_off(client, sets, player, play):
    client.force_login(player)
    response = _play(client, sets.bonus, play)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert not UserSetPreference.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("game", ["core", "specialty", "exclusive"])
def test_only_a_bonus_or_challenge_subset_takes_an_opt_in(client, sets, player, game):
    client.force_login(player)
    assert _play(client, getattr(sets, game), "on").status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_opting_in_only_answers_posts(client, sets, player):
    client.force_login(player)
    response = client.get(f"/games/{sets.bonus.pk}/play/")
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


# --- Leaderboards tab ---


@pytest.mark.django_db
def test_the_leaderboards_tab_lists_the_subsets_boards_after_the_core_ones(client, sets):
    Leaderboard.objects.create(game=sets.bonus, title="Bonus board", mem_addr="STA:0=1")
    Leaderboard.objects.create(game=sets.core, title="Core board", mem_addr="STA:0=1")
    body = client.get(
        f"/games/{sets.core.pk}/panel/leaderboards/", HTTP_ACCEPT_LANGUAGE="en"
    ).content.decode()
    assert body.index("Core board") < body.index("Bonus board")
    bonus_row = body[body.index("Bonus board") :]
    assert ">Bonus subset</span>" in bonus_row[: bonus_row.index("</div>")]
    assert "subset</span>" not in body[: body.index("Bonus board")]


# --- New subset ---


@pytest.mark.django_db
def test_only_staff_get_the_new_subset_button(client, sets, player, staff):
    new_subset = f'href="/games/{sets.core.pk}/subsets/new/"'
    client.force_login(player)
    assert new_subset not in _page(client, sets.core)
    client.force_login(staff)
    assert new_subset in _page(client, sets.core)


@pytest.mark.django_db
def test_staff_add_a_subset_from_the_game_page(client, sets, staff):
    client.force_login(staff)
    assert client.get(f"/games/{sets.core.pk}/subsets/new/").status_code == HTTPStatus.OK

    response = client.post(
        f"/games/{sets.core.pk}/subsets/new/",
        {"set_type": SET_TYPE_CHALLENGE, "set_title": "No Damage", "description": "Ouch"},
    )

    subset = Game.objects.get(set_title="No Damage")
    assert response["Location"] == f"/games/{sets.core.pk}/#set-{subset.pk}"
    assert subset.parent_game == sets.core
    assert subset.console == sets.core.console
    assert subset.set_type == SET_TYPE_CHALLENGE
    assert subset.title == f"{CORE_TITLE} [Subset - No Damage]"
    assert "Ouch" in _section(_page(client, sets.core), subset)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"set_type": "", "set_title": "No Damage"}, "set_type"),
        ({"set_type": SET_TYPE_BONUS, "set_title": ""}, "set_title"),
        ({"set_type": "core", "set_title": "No Damage"}, "set_type"),
    ],
)
def test_a_new_subset_needs_a_type_and_a_title(client, sets, staff, fields, field):
    client.force_login(staff)
    subsets = Game.objects.filter(parent_game=sets.core).count()
    response = client.post(f"/games/{sets.core.pk}/subsets/new/", fields)
    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].errors[field]
    assert Game.objects.filter(parent_game=sets.core).count() == subsets


@pytest.mark.django_db
def test_only_staff_add_subsets(client, sets, player):
    path = f"/games/{sets.core.pk}/subsets/new/"
    anonymous = client.get(path)
    assert anonymous.status_code == HTTPStatus.FOUND
    assert anonymous["Location"].startswith("/login/")
    client.force_login(player)
    assert client.get(path).status_code == HTTPStatus.FORBIDDEN
    assert client.post(path, {"set_type": SET_TYPE_BONUS, "set_title": "X"}).status_code == (
        HTTPStatus.FORBIDDEN
    )


@pytest.mark.django_db
def test_a_subset_takes_no_subsets(client, sets, staff):
    client.force_login(staff)
    response = client.get(f"/games/{sets.bonus.pk}/subsets/new/")
    assert response.status_code == HTTPStatus.NOT_FOUND
