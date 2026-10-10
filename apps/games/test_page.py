"""The public game page and its HTMX tabs, over real achievements, unlocks, leaderboards and
sessions."""

import re
from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import API_TOKEN_HEX_LENGTH
from apps.achievements.models import Achievement, UserUnlock
from apps.api.handlers import (
    ACHIEVEMENT_FLAGS_CORE,
    ACHIEVEMENT_FLAGS_UNOFFICIAL,
    API_TOKEN_LIFETIME,
)
from apps.games.models import Console, Game, PlayerGame
from apps.games.page import RECENT_PLAYERS_SHOWN, VALID_FILTERS, VALID_TABS
from apps.images.catalog import avatar_path, badge_path, versioned_game_icon_path
from apps.leaderboards.models import Leaderboard, LeaderboardEntry

User = get_user_model()

PLAYSTATION_RA_ID = 12
SYSTEM_ACCOUNT = "ra-import"
PASSWORD = "pw-secret-123"
UNKNOWN_GAME_ID = 999_999
BADGE_NAME = "00042"
FIRST_POINTS = 10
DEFAULT_POINTS = 5
UNOFFICIAL_POINTS = 25
LARGE_POINTS = 1500
ENTRY_SCORE = 100
RIVAL_TOKEN = "f" * API_TOKEN_HEX_LENGTH
FILTERS_GROUP = "Filter achievements"
# More rows than the page lists, so the cut is visible.
EXTRA_ROWS = 2


def _user(username, is_active=True):
    return User.objects.create_user(username=username, password=PASSWORD, is_active=is_active)


def _achievement(
    game, title, points=DEFAULT_POINTS, status=Achievement.STATUS_OFFICIAL, author=None
):
    return Achievement.objects.create(
        game=game,
        author=author or User.objects.get(username=SYSTEM_ACCOUNT),
        title=title,
        description=f"{title} description",
        points=points,
        mem_addr="0xH0001=1",
        status=status,
    )


def _unlock(user, achievement, hardcore, unlocked_at=None):
    """Records an unlock as `handle_awardachievement` does: hardcore writes the softcore twin."""
    unlocked_at = unlocked_at or timezone.now()
    modes = (False, True) if hardcore else (False,)
    for mode in modes:
        UserUnlock.objects.create(
            user=user, achievement=achievement, hardcore=mode, unlocked_at=unlocked_at
        )


def _get(client, path, **params):
    return client.get(path, params, HTTP_ACCEPT_LANGUAGE="en")


def _page(client, game):
    response = _get(client, f"/games/{game.pk}/")
    assert response.status_code == HTTPStatus.OK
    return response.content.decode()


def _panel(client, game, tab, **params):
    response = _get(client, f"/games/{game.pk}/panel/{tab}/", **params)
    assert response.status_code == HTTPStatus.OK
    return response.content.decode()


def _pressed(body, group):
    """The `hx-get` URL of the one pressed chip in the chip group labelled `group`."""
    start = body.index(f'aria-label="{group}"')
    chips = body[start : body.index("</div>", start)]
    assert chips.count('aria-pressed="true"') == 1
    pressed = chips.index('aria-pressed="true"')
    url_start = chips.index('hx-get="', pressed) + len('hx-get="')
    return chips[url_start : chips.index('"', url_start)]


def _row(body, title):
    """The markup of the achievement row titled `title`: from its badge to its title."""
    end = body.index(f">{title}<")
    return body[body.rindex("<img", 0, end) : end]


@pytest.fixture
def playstation(db):
    _user(SYSTEM_ACCOUNT, is_active=False)
    return Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")


@pytest.fixture
def crash(playstation):
    return Game.objects.create(
        title="Crash Bandicoot", console=playstation, description="A bandicoot <b>spins</b>."
    )


@pytest.fixture
def player(db):
    return _user("teste")


@pytest.fixture
def achievements(crash):
    return {
        "first": _achievement(crash, "Official one", FIRST_POINTS),
        "second": _achievement(crash, "Official two"),
        "third": _achievement(crash, "Official three"),
    }


# --- Header ---


@pytest.mark.django_db
def test_game_page_shows_the_game_and_its_official_totals(client, crash, achievements):
    _achievement(crash, "Unofficial one", UNOFFICIAL_POINTS, status=Achievement.STATUS_UNOFFICIAL)
    body = _page(client, crash)
    assert "<h1" in body and "Crash Bandicoot</h1>" in body
    assert versioned_game_icon_path(crash) in body
    assert "PS1" in body and "PlayStation" in body
    assert "A bandicoot &lt;b&gt;spins&lt;/b&gt;." in body
    official_points = sum(achievement.points for achievement in achievements.values())
    assert f'text-txt">{len(achievements)}</div>' in body
    assert f'text-gold">{official_points}</div>' in body


@pytest.mark.django_db
def test_game_page_groups_points_in_brazilian_portuguese(client, crash):
    _achievement(crash, "Big one", LARGE_POINTS)
    body = client.get(f"/games/{crash.pk}/", HTTP_ACCEPT_LANGUAGE="pt-br").content.decode()
    assert 'text-gold">1.500</div>' in body
    assert "Conquistas" in body and "Jogadores recentes" in body


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        f"/games/{UNKNOWN_GAME_ID}/",
        f"/games/{UNKNOWN_GAME_ID}/panel/players/",
        f"/games/{UNKNOWN_GAME_ID}/panel/achievements/?filter=bogus",
    ],
)
def test_unknown_game_answers_404(client, crash, path):
    assert client.get(path).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_game_page_rejects_writes(client, crash):
    assert client.post(f"/games/{crash.pk}/").status_code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_game_without_achievements_shows_an_honest_empty_state(client, crash):
    body = _page(client, crash)
    assert "No achievements yet" in body
    assert 'text-txt">0</div>' in body


# --- Achievements: official and unofficial sections ---

AUTHOR = "author"
OTHER_USER = "other"
ANONYMOUS = "anonymous"
VIEWERS = [AUTHOR, OTHER_USER, ANONYMOUS]
UNOFFICIAL_TITLE = "Author unofficial"


@pytest.fixture
def author(db):
    return _user("unofficial-author")


@pytest.fixture
def authors_unofficial(crash, author):
    return _achievement(
        crash,
        UNOFFICIAL_TITLE,
        UNOFFICIAL_POINTS,
        status=Achievement.STATUS_UNOFFICIAL,
        author=author,
    )


@pytest.fixture
def rival(db):
    rival = _user("someone-else")
    rival.api_token = RIVAL_TOKEN
    rival.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    rival.save(update_fields=["api_token", "api_token_expires_at"])
    return rival


@pytest.fixture
def view_as(client, author, rival):
    """Logs `client` in as one of `VIEWERS`."""

    def log_in(viewer):
        if viewer == AUTHOR:
            client.force_login(author)
        elif viewer == OTHER_USER:
            client.force_login(rival)
        elif viewer == ANONYMOUS:
            client.logout()
        else:
            raise ValueError(f"Unknown viewer: {viewer}")

    return log_in


def _status_chip(body, title):
    """The markup of the row titled `title` after its title: its status chip."""
    row = body[body.index(f">{title}<") :]
    return row[: row.index("</div>")]


def _served_flags(client, requester, token, game):
    data = client.post(
        "/dorequest.php",
        {"r": "achievementsets", "u": requester.username, "t": token, "g": game.pk},
    ).json()
    return {a["Title"]: a["Flags"] for a in data["Sets"][0]["Achievements"]}


@pytest.mark.django_db
@pytest.mark.parametrize("viewer", VIEWERS)
def test_every_viewer_sees_unofficial_achievements_collapsed_after_the_official_ones(
    client, crash, achievements, authors_unofficial, view_as, viewer
):
    view_as(viewer)
    body = _page(client, crash)
    core = body.index(">Core set\n")
    unofficial = body.index(f'<details id="unofficial-{crash.pk}"')
    assert core < body.index(">Official one<") < unofficial
    assert body.index(">Official one<") < body.index(">Official two<")
    assert body.index(">Official three<") < unofficial < body.index(f">{UNOFFICIAL_TITLE}<")
    assert f'<details id="unofficial-{crash.pk}" class="border-t border-line">' in body


@pytest.mark.django_db
def test_a_set_without_unofficial_achievements_has_no_unofficial_part(client, crash, achievements):
    body = _page(client, crash)
    assert "unofficial-" not in body
    assert ">Official one<" in body


@pytest.mark.django_db
def test_a_set_with_only_unofficial_achievements_lists_them_collapsed(
    client, crash, authors_unofficial
):
    body = _page(client, crash)
    assert body.index(f'<details id="unofficial-{crash.pk}"') < body.index(f">{UNOFFICIAL_TITLE}<")
    assert "No achievements yet" not in body


@pytest.mark.django_db
def test_anonymous_visitor_sees_no_filters_or_unlock_state(client, crash, achievements):
    body = _page(client, crash)
    assert "Filter achievements" not in body
    assert "?filter=unlocked" not in body
    assert badge_path(achievements["second"].badge_name) in body
    assert "_lock.png" not in body


@pytest.mark.django_db
def test_unofficial_achievements_stay_out_of_the_totals(
    client, crash, achievements, authors_unofficial
):
    page = _page(client, crash)
    official_points = sum(achievement.points for achievement in achievements.values())
    assert f'text-txt">{len(achievements)}</div>' in page
    assert f'text-gold">{official_points}</div>' in page


@pytest.mark.django_db
def test_every_achievement_carries_its_status_chip(client, crash, achievements, authors_unofficial):
    body = _page(client, crash)
    for title in ("Official one", "Official two", "Official three"):
        assert 'text-brand">Official</span>' in _status_chip(body, title)
    assert 'text-gold">Unofficial</span>' in _status_chip(body, UNOFFICIAL_TITLE)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("language", "core", "unofficial", "chip"),
    [
        ("en", "Core set", "Unofficial", "Official"),
        ("pt-br", "Set principal", "Não oficiais", "Oficial"),
    ],
)
def test_sections_and_chips_follow_the_viewer_language(
    client, crash, achievements, authors_unofficial, language, core, unofficial, chip
):
    body = client.get(f"/games/{crash.pk}/", HTTP_ACCEPT_LANGUAGE=language).content.decode()
    assert re.search(rf'bg-brand"></span>{core}\s*</h2>', body)
    assert re.search(rf'text-gold">{unofficial} <span', body)
    assert f">{chip}</span>" in _status_chip(body, "Official one")


@pytest.mark.django_db
def test_making_an_achievement_official_moves_it_and_serves_it_as_core(
    client, admin_client, crash, authors_unofficial, rival
):
    assert _served_flags(client, rival, RIVAL_TOKEN, crash) == {
        UNOFFICIAL_TITLE: ACHIEVEMENT_FLAGS_UNOFFICIAL
    }

    admin_client.post(
        "/admin/achievements/achievement/",
        {"action": "make_official", "_selected_action": [authors_unofficial.pk]},
    )

    body = _page(client, crash)
    assert "unofficial-" not in body
    assert ">Official</span>" in _status_chip(body, UNOFFICIAL_TITLE)
    assert _served_flags(client, rival, RIVAL_TOKEN, crash) == {
        UNOFFICIAL_TITLE: ACHIEVEMENT_FLAGS_CORE
    }


@pytest.mark.django_db
def test_the_filter_applies_to_both_sections(client, crash, achievements, player):
    _achievement(crash, "Unofficial one", status=Achievement.STATUS_UNOFFICIAL)
    _unlock(player, achievements["first"], hardcore=True)
    client.force_login(player)

    locked = _panel(client, crash, "achievements", filter="locked")
    unlocked = _panel(client, crash, "achievements", filter="unlocked")

    assert ">Unofficial one<" in locked and ">Official one<" not in locked
    assert ">Official one<" in unlocked and ">Unofficial one<" not in unlocked
    assert _pressed(locked, FILTERS_GROUP) == f"/games/{crash.pk}/panel/achievements/?filter=locked"


# --- Achievements: the viewer's unlocks ---


@pytest.mark.django_db
def test_logged_in_user_sees_hardcore_softcore_and_locked_apart(
    client, crash, achievements, player
):
    _unlock(player, achievements["first"], hardcore=True)
    _unlock(player, achievements["second"], hardcore=False)
    client.force_login(player)
    body = _page(client, crash)

    hardcore = _row(body, "Official one")
    assert "border-state-hardcore" in hardcore
    assert badge_path(achievements["first"].badge_name) in hardcore

    softcore = _row(body, "Official two")
    assert "border-state-softcore" in softcore

    locked = _row(body, "Official three")
    assert badge_path(achievements["third"].badge_name, locked=True) in locked
    assert "opacity-60" in locked
    assert body.count('text-state-hardcore">') == 1
    assert body.count('text-state-softcore">') == 1


@pytest.mark.django_db
def test_hardcore_upgrade_of_a_softcore_unlock_shows_as_hardcore(
    client, crash, achievements, player
):
    earlier = timezone.now() - timedelta(days=1)
    UserUnlock.objects.create(
        user=player, achievement=achievements["second"], hardcore=False, unlocked_at=earlier
    )
    UserUnlock.objects.create(user=player, achievement=achievements["second"], hardcore=True)
    client.force_login(player)
    assert "border-state-hardcore" in _row(_page(client, crash), "Official two")


@pytest.mark.django_db
def test_another_users_unlocks_do_not_highlight_the_viewers_page(
    client, crash, achievements, player
):
    _unlock(_user("rival"), achievements["first"], hardcore=True)
    client.force_login(player)
    body = _page(client, crash)
    assert "border-state-hardcore" not in body
    assert badge_path(achievements["first"].badge_name, locked=True) in body


# --- Achievements: HTMX filters ---


@pytest.mark.django_db
def test_logged_in_user_gets_the_filters_with_all_active(client, crash, achievements, player):
    client.force_login(player)
    body = _page(client, crash)
    for slug in VALID_FILTERS:
        assert f'"/games/{crash.pk}/panel/achievements/?filter={slug}"' in body
    assert _pressed(body, FILTERS_GROUP).endswith("filter=all")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("achievement_filter", "shown", "hidden"),
    [
        ("all", ["Official one", "Official two", "Official three"], []),
        ("unlocked", ["Official one", "Official two"], ["Official three"]),
        ("locked", ["Official three"], ["Official one", "Official two"]),
    ],
)
def test_filter_returns_a_fragment_with_the_matching_achievements(
    client, crash, achievements, player, achievement_filter, shown, hidden
):
    _unlock(player, achievements["first"], hardcore=True)
    _unlock(player, achievements["second"], hardcore=False)
    client.force_login(player)
    body = _panel(client, crash, "achievements", filter=achievement_filter)
    assert "<!DOCTYPE" not in body
    assert "<h1" not in body
    for title in shown:
        assert f">{title}<" in body
    for title in hidden:
        assert f">{title}<" not in body
    assert _pressed(body, FILTERS_GROUP).endswith(f"filter={achievement_filter}")


@pytest.mark.django_db
def test_unlocked_filter_with_nothing_unlocked_says_so(client, crash, player):
    _achievement(crash, "Only one")
    client.force_login(player)
    body = _panel(client, crash, "achievements", filter="unlocked")
    assert "No achievements unlocked yet" in body


@pytest.mark.django_db
def test_locked_filter_with_everything_unlocked_says_so(client, crash, player):
    _unlock(player, _achievement(crash, "Only one"), hardcore=False)
    client.force_login(player)
    body = _panel(client, crash, "achievements", filter="locked")
    assert "Every achievement unlocked" in body


@pytest.mark.django_db
@pytest.mark.parametrize("achievement_filter", VALID_FILTERS)
def test_every_filter_on_a_game_without_achievements_says_there_are_none(
    client, crash, player, achievement_filter
):
    client.force_login(player)
    body = _panel(client, crash, "achievements", filter=achievement_filter)
    assert "No achievements yet" in body
    assert "Every achievement unlocked" not in body


@pytest.mark.django_db
def test_unknown_filter_answers_400_in_the_viewer_language(client, crash, player):
    client.force_login(player)
    response = client.get(
        f"/games/{crash.pk}/panel/achievements/", {"filter": "bogus"}, HTTP_ACCEPT_LANGUAGE="pt-br"
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.content.decode() == "Filtro de conquistas desconhecido"


# --- Tabs ---


@pytest.mark.django_db
def test_tabs_load_each_panel_through_htmx_with_achievements_active(client, crash):
    body = _page(client, crash)
    for tab in VALID_TABS:
        assert f'hx-get="/games/{crash.pk}/panel/{tab}/" hx-target="#game-tabs"' in body
    assert body.count('aria-selected="true"') == 1
    selected = body.index('aria-selected="true"')
    assert "panel/achievements/" in body[selected : body.index("</button>", selected)]


@pytest.mark.django_db
@pytest.mark.parametrize("tab", VALID_TABS)
def test_panel_returns_the_tab_bar_with_its_tab_active(client, crash, tab):
    body = _panel(client, crash, tab)
    assert "<!DOCTYPE" not in body
    selected = body.index('aria-selected="true"')
    assert f"panel/{tab}/" in body[selected : body.index("</button>", selected)]


@pytest.mark.django_db
@pytest.mark.parametrize("tab", ["wall", "bogus"])
def test_unknown_tab_answers_404(client, crash, tab):
    assert client.get(f"/games/{crash.pk}/panel/{tab}/").status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("tab", "english", "portuguese"),
    [
        ("achievements", "No achievements yet", "Nenhuma conquista ainda"),
        ("leaderboards", "No leaderboards yet", "Nenhum placar ainda"),
        ("players", "Nobody has played it yet", "Ninguém jogou ainda"),
    ],
)
@pytest.mark.parametrize("language", ["en", "pt-br"])
def test_panels_render_in_each_language(client, crash, tab, english, portuguese, language):
    response = client.get(f"/games/{crash.pk}/panel/{tab}/", HTTP_ACCEPT_LANGUAGE=language)
    assert response.status_code == HTTPStatus.OK
    if language == "en":
        assert english in response.content.decode()
    else:
        assert portuguese in response.content.decode()


@pytest.mark.django_db
def test_leaderboards_tab_lists_the_games_boards_with_active_entries(
    client, crash, playstation, player
):
    fastest = Leaderboard.objects.create(
        game=crash, title="Fastest beach", description="Clear the beach", mem_addr="STA:0=1"
    )
    Leaderboard.objects.create(game=crash, title="Most wumpa", mem_addr="STA:0=1")
    other_game = Game.objects.create(title="Ape Escape", console=playstation)
    Leaderboard.objects.create(game=other_game, title="Other board", mem_addr="STA:0=1")
    LeaderboardEntry.objects.create(leaderboard=fastest, user=player, score=ENTRY_SCORE)
    LeaderboardEntry.objects.create(
        leaderboard=fastest, user=User.objects.get(username=SYSTEM_ACCOUNT), score=ENTRY_SCORE
    )
    body = _panel(client, crash, "leaderboards")
    assert body.index("Fastest beach") < body.index("Most wumpa")
    assert "Clear the beach" in body
    assert "1 entry" in body
    assert "0 entries" in body
    assert "Other board" not in body


@pytest.mark.django_db
def test_players_tab_lists_active_players_most_recent_first(client, crash, achievements, player):
    now = timezone.now()
    rival = _user("rival")
    PlayerGame.objects.create(user=player, game=crash, last_played_at=now - timedelta(days=1))
    PlayerGame.objects.create(user=rival, game=crash, last_played_at=now)
    PlayerGame.objects.create(user=_user("gone", is_active=False), game=crash, last_played_at=now)
    hardcore_unlocks = [achievements["first"]]
    softcore_unlocks = [achievements["second"]]
    for achievement in hardcore_unlocks:
        _unlock(player, achievement, hardcore=True)
    for achievement in softcore_unlocks:
        _unlock(player, achievement, hardcore=False)
    _achievement(crash, "Unofficial", status=Achievement.STATUS_UNOFFICIAL, author=player)
    unlocked = len(hardcore_unlocks) + len(softcore_unlocks)
    body = _panel(client, crash, "players")
    assert body.index(">rival<") < body.index(">teste<")
    assert 'href="/users/teste/"' in body
    assert avatar_path("teste") in body
    expected = f"{unlocked}/{len(achievements)} achievements ({len(hardcore_unlocks)} hardcore)"
    assert expected in body
    assert "gone" not in body


@pytest.mark.django_db
def test_players_tab_shows_only_the_latest_players(client, crash):
    now = timezone.now()
    for index in range(RECENT_PLAYERS_SHOWN + EXTRA_ROWS):
        PlayerGame.objects.create(
            user=_user(f"player-{index}"), game=crash, last_played_at=now - timedelta(minutes=index)
        )
    body = _panel(client, crash, "players")
    assert body.count('href="/users/player-') == RECENT_PLAYERS_SHOWN
    assert ">player-0<" in body
    assert f">player-{RECENT_PLAYERS_SHOWN}<" not in body


# --- Performance and links ---


@pytest.mark.django_db
def test_game_page_queries_do_not_grow_with_achievements(client, crash, player):
    client.force_login(player)

    def queries():
        with CaptureQueriesContext(connection) as captured:
            _page(client, crash)
        return len(captured)

    _unlock(player, _achievement(crash, "First"), hardcore=True)
    baseline = queries()
    for index in range(EXTRA_ROWS):
        _unlock(player, _achievement(crash, f"More {index}"), hardcore=False)
        _achievement(
            crash, f"Unofficial {index}", status=Achievement.STATUS_UNOFFICIAL, author=player
        )
    assert queries() == baseline


@pytest.mark.django_db
def test_home_and_profile_link_their_games_to_the_game_page(client, crash, achievements, player):
    _unlock(player, achievements["first"], hardcore=True)
    PlayerGame.objects.create(user=player, game=crash)
    player.softcore_points = FIRST_POINTS
    player.save(update_fields=["softcore_points"])
    game_link = f'href="/games/{crash.pk}/"'
    for path in ["/", "/users/teste/", "/users/teste/panel/games/", "/users/teste/panel/progress/"]:
        assert game_link in _get(client, path).content.decode(), path
