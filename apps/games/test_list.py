"""The games list and the results fragment its HTMX search and filters swap in."""

from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.achievements.models import Achievement
from apps.games.forms import TITLE_SEARCH_MAX_LENGTH
from apps.games.listing import GAMES_PER_PAGE
from apps.games.models import Console, Game, PlayerGame
from apps.images.catalog import versioned_game_icon_path

User = get_user_model()

PLAYSTATION_RA_ID = 12
NINTENDO_64_RA_ID = 2
SYSTEM_ACCOUNT = "ra-import"
PASSWORD = "pw-secret-123"
LIST_PATH = "/games/"
RESULTS_PATH = "/games/results/"
PATHS = [LIST_PATH, RESULTS_PATH]
# The desktop nav, the mobile nav, the footer and the home hero.
GAMES_LINKS_ON_HOME = 4
# The desktop nav and the mobile nav.
SEARCH_LINKS_PER_PAGE = 2
EXTRA_GAMES = 1
UNKNOWN_CONSOLE_ID = 999_999
SPYRO_ACHIEVEMENTS = 3
CRASH_ACHIEVEMENTS = 2
# Crash, Spyro and Mario: the `catalog` game with only an unofficial achievement is not listed.
OFFICIAL_CATALOG_GAMES = 3
# `many_games` fills one page and spills onto a second.
LAST_PAGE = 2


def _user(username, is_active=True):
    return User.objects.create_user(username=username, password=PASSWORD, is_active=is_active)


def _achievements(game, count, status=Achievement.STATUS_OFFICIAL):
    for index in range(count):
        Achievement.objects.create(
            game=game,
            author=User.objects.get(username=SYSTEM_ACCOUNT),
            title=f"{game.title} {index}",
            description="",
            points=1,
            mem_addr="0xH0001=1",
            status=status,
        )


def _game(title, console, official=1):
    game = Game.objects.create(title=title, console=console)
    _achievements(game, official)
    return game


def _get(client, path, params=None, language="en"):
    return client.get(path, params or {}, HTTP_ACCEPT_LANGUAGE=language)


def _titles(resp):
    return [card["game"].title for card in resp.context["cards"]]


@pytest.fixture
def playstation(db):
    _user(SYSTEM_ACCOUNT, is_active=False)
    return Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")


@pytest.fixture
def nintendo_64(db):
    return Console.objects.create(ra_id=NINTENDO_64_RA_ID, name="Nintendo 64", short_name="N64")


@pytest.fixture
def catalog(playstation, nintendo_64):
    """Crash and Spyro on PS1 with official sets, Mario 64 on N64, and a PS1 game whose only
    achievement is unofficial."""
    crash = _game("Crash Bandicoot", playstation, CRASH_ACHIEVEMENTS)
    spyro = _game("Spyro the Dragon", playstation, SPYRO_ACHIEVEMENTS)
    mario = _game("Super Mario 64", nintendo_64)
    unofficial_only = _game("Ape Escape", playstation, official=0)
    _achievements(unofficial_only, 1, status=Achievement.STATUS_UNOFFICIAL)
    return {"crash": crash, "spyro": spyro, "mario": mario, "unofficial_only": unofficial_only}


# --- Cards and defaults ---


@pytest.mark.django_db
@pytest.mark.parametrize("path", PATHS)
def test_list_shows_games_with_an_official_set_by_title(client, catalog, path):
    resp = _get(client, path)

    assert resp.status_code == HTTPStatus.OK
    assert _titles(resp) == ["Crash Bandicoot", "Spyro the Dragon", "Super Mario 64"]
    body = resp.content.decode()
    crash = catalog["crash"]
    assert f'href="/games/{crash.pk}/"' in body
    assert f'src="{versioned_game_icon_path(crash)}"' in body
    assert f"{CRASH_ACHIEVEMENTS} achievements" in body
    assert ">PS1<" in body
    assert f"{OFFICIAL_CATALOG_GAMES} games" in body
    assert "Ape Escape" not in body


@pytest.mark.django_db
def test_minimum_of_zero_lists_games_without_an_official_set(client, catalog):
    resp = _get(client, LIST_PATH, {"min_achievements": 0})

    assert "Ape Escape" in _titles(resp)
    assert "0 achievements" in resp.content.decode()


@pytest.mark.django_db
def test_minimum_achievements_counts_only_official_ones(client, catalog):
    _achievements(catalog["crash"], SPYRO_ACHIEVEMENTS, status=Achievement.STATUS_UNOFFICIAL)

    resp = _get(client, LIST_PATH, {"min_achievements": SPYRO_ACHIEVEMENTS})

    assert _titles(resp) == ["Spyro the Dragon"]


# --- Search and filters ---


@pytest.mark.django_db
@pytest.mark.parametrize("path", PATHS)
def test_searching_crash_finds_crash_bandicoot(client, catalog, path):
    resp = _get(client, path, {"q": "crash"})

    assert _titles(resp) == ["Crash Bandicoot"]


@pytest.mark.django_db
def test_console_filter_keeps_only_that_consoles_games(client, catalog, nintendo_64):
    resp = _get(client, LIST_PATH, {"console": nintendo_64.pk})

    assert _titles(resp) == ["Super Mario 64"]


@pytest.mark.django_db
def test_search_and_filters_combine(client, catalog, playstation):
    params = {"q": "o", "console": playstation.pk, "min_achievements": SPYRO_ACHIEVEMENTS}

    assert _titles(_get(client, LIST_PATH, params)) == ["Spyro the Dragon"]


@pytest.mark.django_db
def test_no_match_shows_an_empty_state_that_clears_the_filters(client, catalog):
    body = _get(client, RESULTS_PATH, {"q": "zelda"}).content.decode()

    assert "No games match these filters" in body
    assert f'href="{LIST_PATH}"' in body


@pytest.mark.django_db
def test_without_official_sets_the_list_says_so(client, playstation):
    body = _get(client, LIST_PATH).content.decode()

    assert "No official sets yet" in body
    assert "No games match these filters" not in body


@pytest.mark.django_db
@pytest.mark.parametrize(
    "params",
    [
        {"console": UNKNOWN_CONSOLE_ID},
        {"min_achievements": -1},
        {"min_achievements": "many"},
        {"order": "rating"},
        {"q": "x" * (TITLE_SEARCH_MAX_LENGTH + 1)},
    ],
)
@pytest.mark.parametrize("path", PATHS)
def test_invalid_filters_answer_400(client, catalog, path, params):
    resp = _get(client, path, params)

    assert resp.status_code == HTTPStatus.BAD_REQUEST
    assert "HX-Replace-Url" not in resp.headers


# --- Ordering ---


@pytest.mark.django_db
def test_ordering_by_most_achievements(client, catalog):
    resp = _get(client, LIST_PATH, {"order": "achievements"})

    assert _titles(resp) == ["Spyro the Dragon", "Crash Bandicoot", "Super Mario 64"]


@pytest.mark.django_db
def test_ordering_by_most_players_counts_active_players(client, catalog):
    for username in ("first", "second"):
        PlayerGame.objects.create(user=_user(username), game=catalog["mario"])
    PlayerGame.objects.create(user=_user("third"), game=catalog["crash"])
    for username in ("banned", "suspended"):
        PlayerGame.objects.create(user=_user(username, is_active=False), game=catalog["spyro"])

    resp = _get(client, LIST_PATH, {"order": "players"})

    assert _titles(resp) == ["Super Mario 64", "Crash Bandicoot", "Spyro the Dragon"]


@pytest.mark.django_db
def test_ordering_alphabetically_is_the_default(client, catalog):
    explicit = _titles(_get(client, LIST_PATH, {"order": "title"}))

    assert explicit == _titles(_get(client, LIST_PATH))


# --- Pagination ---


@pytest.fixture
def many_games(playstation):
    for index in range(GAMES_PER_PAGE + EXTRA_GAMES):
        _game(f"Game {index:02d}", playstation)


@pytest.mark.django_db
def test_list_pages_by_the_page_size(client, many_games):
    first = _get(client, LIST_PATH)
    second = _get(client, LIST_PATH, {"page": LAST_PAGE})

    assert len(first.context["cards"]) == GAMES_PER_PAGE
    assert _titles(second) == [f"Game {GAMES_PER_PAGE:02d}"]
    assert f"Page {LAST_PAGE} of {LAST_PAGE}" in second.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("path", PATHS)
def test_page_links_keep_the_search_and_filters(client, many_games, playstation, path):
    params = {"q": "game", "console": playstation.pk, "order": "achievements"}

    body = _get(client, path, params).content.decode()

    query = f"q=game&amp;console={playstation.pk}&amp;order=achievements&amp;page={LAST_PAGE}"
    assert f'href="{LIST_PATH}?{query}"' in body
    assert f'hx-get="{RESULTS_PATH}?{query}"' in body


@pytest.mark.django_db
@pytest.mark.parametrize("page", [str(LAST_PAGE + 1), "0", "last-one"])
@pytest.mark.parametrize("path", PATHS)
def test_unknown_page_answers_404(client, many_games, path, page):
    assert _get(client, path, {"page": page}).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_queries_do_not_grow_with_cards(client, playstation):
    def query_count():
        with CaptureQueriesContext(connection) as queries:
            _get(client, LIST_PATH)
        return len(queries)

    _game("Crash Bandicoot", playstation)
    baseline = query_count()
    for index in range(GAMES_PER_PAGE):
        _game(f"Game {index:02d}", playstation)

    assert query_count() == baseline


# --- HTMX ---


@pytest.mark.django_db
def test_list_form_swaps_the_results_through_htmx_after_300_ms(client, catalog):
    body = _get(client, LIST_PATH).content.decode()

    assert f'action="{LIST_PATH}" method="get"' in body
    assert f'hx-get="{RESULTS_PATH}"' in body
    assert 'hx-trigger="input changed delay:300ms, submit"' in body
    assert 'hx-target="#games-results"' in body
    assert body.count('id="games-results"') == 1


@pytest.mark.django_db
def test_results_fragment_is_the_bare_results_and_replaces_the_list_url(client, catalog):
    resp = _get(client, RESULTS_PATH, {"q": "crash", "page": 1})

    body = resp.content.decode()
    assert body.lstrip().startswith('<div id="games-results"')
    assert "<html" not in body
    assert "<form" not in body
    assert resp.headers["HX-Replace-Url"] == f"{LIST_PATH}?q=crash&page=1"


@pytest.mark.django_db
def test_results_fragment_without_a_query_replaces_the_bare_list_url(client, catalog):
    assert _get(client, RESULTS_PATH).headers["HX-Replace-Url"] == LIST_PATH


@pytest.mark.django_db
@pytest.mark.parametrize("path", PATHS)
def test_list_rejects_writes(client, catalog, path):
    assert client.post(path).status_code == HTTPStatus.METHOD_NOT_ALLOWED


# --- Navigation and language ---


@pytest.mark.django_db
def test_nav_footer_and_home_link_the_games_list(client, catalog):
    resp = _get(client, "/")

    body = resp.content.decode()
    assert body.count(f'href="{LIST_PATH}"') == GAMES_LINKS_ON_HOME
    assert body.count(f'href="{LIST_PATH}#game-search"') == SEARCH_LINKS_PER_PAGE
    assert 'id="game-search"' in _get(client, LIST_PATH).content.decode()


@pytest.mark.django_db
def test_list_is_translated_to_brazilian_portuguese(client, catalog):
    body = _get(client, LIST_PATH, language="pt-br").content.decode()

    assert f"{OFFICIAL_CATALOG_GAMES} jogos" in body
    assert f"{CRASH_ACHIEVEMENTS} conquistas" in body
    assert "Mínimo de conquistas" in body
    assert "Ordem alfabética" in body
