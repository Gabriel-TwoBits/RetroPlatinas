"""The public leaderboard page: active users' entries best first, a page at a time, the viewer's
own entry highlighted or set apart, and scores as the emulator shows them."""

from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model

from apps.games.models import Console, Game
from apps.images.catalog import avatar_path
from apps.leaderboards.formatting import format_score
from apps.leaderboards.models import Leaderboard, LeaderboardEntry
from apps.leaderboards.page import ENTRIES_PER_PAGE

User = get_user_model()

PLAYSTATION_RA_ID = 12
PASSWORD = "pw-secret-123"
UNKNOWN_ID = 999_999
VIEWER_MARK = 'aria-current="true"'
YOUR_POSITION = "Your position"
RANKING_LIST = 'id="leaderboard-entries"'
# Frames that format.c renders as "1:23.33".
TIME_SCORE = 5000
TIME_SHOWN = "1:23.33"
# More entries than one page holds, so the cut is visible.
EXTRA_ENTRIES = 2
BOARD_SIZE = ENTRIES_PER_PAGE + EXTRA_ENTRIES


def _user(username, is_active=True):
    return User.objects.create_user(username=username, password=PASSWORD, is_active=is_active)


def _entry(leaderboard, user, score):
    return LeaderboardEntry.objects.create(leaderboard=leaderboard, user=user, score=score)


def _url(leaderboard, game=None):
    game_id = leaderboard.game_id if game is None else game.pk
    return f"/games/{game_id}/leaderboards/{leaderboard.pk}/"


def _get(client, path, **params):
    return client.get(path, params, HTTP_ACCEPT_LANGUAGE="en")


def _page(client, leaderboard, **params):
    response = _get(client, _url(leaderboard), **params)
    assert response.status_code == HTTPStatus.OK
    return response.content.decode()


def _ranks(body):
    """The usernames of the board's rows, in order, by their profile links."""
    usernames = []
    position = body.index(RANKING_LIST)
    list_end = body.index("</section>", position)
    marker = 'href="/users/'
    while (start := body.find(marker, position, list_end)) != -1:
        end = body.index("/", start + len(marker))
        usernames.append(body[start + len(marker) : end])
        position = end
    return usernames


def _full_board(leaderboard):
    """`BOARD_SIZE` users scoring 1..BOARD_SIZE, so `player-<n>` holds the n-th best (highest)."""
    users = User.objects.bulk_create(
        User(username=f"player-{position}") for position in range(1, BOARD_SIZE + 1)
    )
    LeaderboardEntry.objects.bulk_create(
        LeaderboardEntry(leaderboard=leaderboard, user=user, score=BOARD_SIZE - index)
        for index, user in enumerate(users)
    )
    return users


@pytest.fixture
def crash(db):
    console = Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


@pytest.fixture
def fastest(crash):
    return Leaderboard.objects.create(
        game=crash,
        title="Fastest beach",
        description="Clear the beach",
        mem_addr="STA:0=1",
        format=Leaderboard.Format.FRAMES,
        lower_is_better=True,
    )


@pytest.fixture
def most(crash):
    return Leaderboard.objects.create(
        game=crash, title="Most wumpa", mem_addr="STA:0=1", format=Leaderboard.Format.VALUE
    )


@pytest.fixture
def player(db):
    return _user("teste")


# --- Routing ---


@pytest.mark.django_db
def test_page_shows_the_leaderboard_and_links_back_to_its_game(client, crash, fastest):
    body = _page(client, fastest)
    assert "Fastest beach</h1>" in body
    assert "Clear the beach" in body
    assert f'href="/games/{crash.pk}/"' in body
    assert "lower is better" in body


@pytest.mark.django_db
def test_unknown_game_or_leaderboard_answers_404(client, crash, fastest):
    unknown_game = f"/games/{UNKNOWN_ID}/leaderboards/{fastest.pk}/"
    unknown_board = f"/games/{crash.pk}/leaderboards/{UNKNOWN_ID}/"
    for path in (unknown_game, unknown_board):
        assert _get(client, path).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_leaderboard_of_another_game_answers_404(client, crash, fastest):
    other_game = Game.objects.create(title="Ape Escape", console=crash.console)
    response = _get(client, _url(fastest, game=other_game))
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
@pytest.mark.parametrize("page", ["0", "3", "abc", "-1"])
def test_page_the_board_does_not_have_answers_404(client, fastest, page):
    _full_board(fastest)
    response = _get(client, _url(fastest), page=page)
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_page_rejects_writes(client, fastest):
    assert client.post(_url(fastest)).status_code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_empty_board_shows_an_honest_empty_state_without_pages(client, fastest):
    body = _page(client, fastest)
    assert "No entries yet" in body
    assert "0 entries" in body
    assert "Leaderboard pages" not in body


# --- Board ---


@pytest.mark.django_db
def test_board_ranks_lower_scores_first_when_lower_is_better(client, fastest):
    for username, score in [("slow", 900), ("fast", 300), ("middle", 600)]:
        _entry(fastest, _user(username), score)
    assert _ranks(_page(client, fastest)) == ["fast", "middle", "slow"]


@pytest.mark.django_db
def test_board_ranks_higher_scores_first_when_higher_is_better(client, most):
    for username, score in [("few", 10), ("many", 90), ("some", 50)]:
        _entry(most, _user(username), score)
    body = _page(client, most)
    assert _ranks(body) == ["many", "some", "few"]
    assert "higher is better" in body


@pytest.mark.django_db
def test_board_shows_scores_as_the_emulator_formats_them(client, fastest):
    rival = _user("rival")
    _entry(fastest, rival, TIME_SCORE)
    body = _page(client, fastest)
    assert TIME_SHOWN in body
    assert f">{TIME_SCORE}<" not in body
    assert avatar_path("rival") in body


@pytest.mark.django_db
def test_tied_scores_share_their_rank(client, most):
    for username, score in [("first", 90), ("tied-a", 50), ("tied-b", 50), ("last", 10)]:
        _entry(most, _user(username), score)
    body = _page(client, most)
    assert ">1</div>" in body
    assert body.count(">2</div>") == 2
    assert ">3</div>" not in body
    assert ">4</div>" in body


@pytest.mark.django_db
def test_inactive_accounts_are_left_off_the_board_and_its_ranks(client, most, player):
    _entry(most, _user("ra-import", is_active=False), 100)
    _entry(most, player, 50)
    body = _page(client, most)
    assert _ranks(body) == ["teste"]
    assert "1 entry" in body
    assert ">1</div>" in body


@pytest.mark.django_db
def test_first_page_shows_the_top_entries_only(client, most):
    _full_board(most)
    body = _page(client, most)
    ranks = _ranks(body)
    assert len(ranks) == ENTRIES_PER_PAGE
    assert ranks[0] == "player-1"
    assert ranks[-1] == f"player-{ENTRIES_PER_PAGE}"
    assert f"{BOARD_SIZE} entries" in body


@pytest.mark.django_db
def test_next_page_continues_the_board_with_its_real_ranks(client, most):
    _full_board(most)
    body = _page(client, most, page="2")
    assert _ranks(body) == [
        f"player-{position}" for position in range(ENTRIES_PER_PAGE + 1, BOARD_SIZE + 1)
    ]
    assert f">{ENTRIES_PER_PAGE + 1}</div>" in body
    assert "Page 2 of 2" in body


@pytest.mark.django_db
def test_pages_navigate_through_htmx_with_a_plain_link_fallback(client, most):
    _full_board(most)
    first = _page(client, most)
    assert 'href="?page=2"' in first
    assert 'hx-get="?page=2"' in first
    assert 'hx-select="#leaderboard-board"' in first
    assert 'hx-push-url="true"' in first
    assert "?page=0" not in first
    second = _page(client, most, page="2")
    assert 'hx-get="?page=1"' in second
    assert "?page=3" not in second


# --- Viewer ---


@pytest.mark.django_db
def test_viewer_entry_on_the_page_is_highlighted_in_place(client, most, player):
    _entry(most, _user("rival"), 90)
    _entry(most, player, 50)
    client.force_login(player)
    body = _page(client, most)
    assert body.count(VIEWER_MARK) == 1
    board = body[body.index(RANKING_LIST) :]
    assert board.index(">rival<") < board.index(VIEWER_MARK) < board.index(">teste<")
    assert YOUR_POSITION not in body


@pytest.mark.django_db
def test_viewer_outside_the_page_sees_their_real_rank_apart(client, most, player):
    _full_board(most)
    _entry(most, player, 0)
    client.force_login(player)
    body = _page(client, most)
    viewer_section = body[body.index(YOUR_POSITION) : body.index(RANKING_LIST)]
    assert ">teste<" in viewer_section
    assert f">{BOARD_SIZE + 1}</div>" in viewer_section
    assert format_score(0, most.format) in viewer_section
    assert "teste" not in _ranks(body)


@pytest.mark.django_db
def test_viewer_without_an_entry_and_anonymous_visitors_get_no_position(client, most, player):
    _entry(most, _user("rival"), 90)
    anonymous = _page(client, most)
    client.force_login(player)
    logged_in = _page(client, most)
    for body in (anonymous, logged_in):
        assert YOUR_POSITION not in body
        assert VIEWER_MARK not in body


@pytest.mark.django_db
def test_another_users_entry_is_not_highlighted(client, most, player):
    _entry(most, _user("rival"), 90)
    client.force_login(player)
    assert VIEWER_MARK not in _page(client, most)


# --- Links and languages ---


@pytest.mark.django_db
def test_game_leaderboards_tab_links_each_board_to_its_page(client, crash, fastest, most):
    body = _get(client, f"/games/{crash.pk}/panel/leaderboards/").content.decode()
    assert f'href="{_url(fastest)}"' in body
    assert f'href="{_url(most)}"' in body


@pytest.mark.django_db
def test_page_renders_in_brazilian_portuguese(client, most, player):
    _full_board(most)
    _entry(most, player, 0)
    client.force_login(player)
    body = client.get(_url(most), HTTP_ACCEPT_LANGUAGE="pt-br").content.decode()
    assert "Sua posição" in body
    assert "Página 1 de 2" in body
    assert "Próxima" in body
    assert "maior é melhor" in body
