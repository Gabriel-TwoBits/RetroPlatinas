"""The public game page and its HTMX tabs, over real achievements, unlocks, leaderboards and
sessions."""

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import API_TOKEN_HEX_LENGTH
from apps.achievements.models import Achievement, UserUnlock
from apps.api.handlers import ACHIEVEMENT_FLAGS_CORE, API_TOKEN_LIFETIME
from apps.games.models import Console, Game, PlayerGame
from apps.games.page import RECENT_PLAYERS_SHOWN, VALID_FILTERS, VALID_SHOW_OPTIONS, VALID_TABS
from apps.images.catalog import avatar_path, badge_path, versioned_game_icon_path
from apps.leaderboards.models import Leaderboard, LeaderboardEntry

User = get_user_model()

PLAYSTATION_RA_ID = 12
SYSTEM_ACCOUNT = "ra-import"
PASSWORD = "pw-secret-123"
UNKNOWN_GAME_ID = 999_999
BADGE_NAME = "00042"
VERIFIED_POINTS = 10
COMMUNITY_POINTS = 5
DRAFT_POINTS = 25
LARGE_POINTS = 1500
ENTRY_SCORE = 100
RIVAL_TOKEN = "f" * API_TOKEN_HEX_LENGTH
SHOW_GROUP = "Show achievements by status"
FILTERS_GROUP = "Filter achievements"
# More rows than the page lists, so the cut is visible.
EXTRA_ROWS = 2


def _user(username, is_active=True):
    return User.objects.create_user(username=username, password=PASSWORD, is_active=is_active)


def _achievement(
    game, title, points=COMMUNITY_POINTS, status=Achievement.STATUS_COMMUNITY, author=None
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
        "verified": _achievement(
            crash, "Verified one", VERIFIED_POINTS, status=Achievement.STATUS_VERIFIED
        ),
        "community": _achievement(crash, "Community one"),
        "other": _achievement(crash, "Community two"),
    }


# --- Header ---


@pytest.mark.django_db
def test_game_page_shows_the_game_and_its_published_totals(client, crash, achievements):
    _achievement(crash, "Somebody's draft", DRAFT_POINTS, status=Achievement.STATUS_DRAFT)
    body = _page(client, crash)
    assert "<h1" in body and "Crash Bandicoot</h1>" in body
    assert versioned_game_icon_path(crash) in body
    assert "PS1" in body and "PlayStation" in body
    assert "A bandicoot &lt;b&gt;spins&lt;/b&gt;." in body
    published_points = sum(achievement.points for achievement in achievements.values())
    assert f'text-txt">{len(achievements)}</div>' in body
    assert f'text-gold">{published_points}</div>' in body


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
def test_game_without_published_achievements_shows_an_honest_empty_state(client, crash):
    body = _page(client, crash)
    assert "No published achievements yet" in body
    assert 'text-txt">0</div>' in body


# --- Achievements: groups and drafts ---


@pytest.mark.django_db
def test_verified_achievements_come_before_community_ones(client, crash, achievements):
    body = _page(client, crash)
    verified = body.index(">Verified\n")
    community = body.index(">Community\n")
    assert verified < body.index(">Verified one<") < community
    assert community < body.index(">Community one<")
    assert body.index(">Community one<") < body.index(">Community two<")


@pytest.mark.django_db
def test_groups_without_achievements_are_hidden(client, crash):
    _achievement(crash, "Community one")
    body = _page(client, crash)
    assert ">Community\n" in body
    assert ">Verified\n" not in body


@pytest.mark.django_db
def test_anonymous_visitor_sees_no_drafts_filters_or_unlock_state(client, crash, achievements):
    _achievement(crash, "Hidden draft", status=Achievement.STATUS_DRAFT)
    body = _page(client, crash)
    assert "Hidden draft" not in body
    assert "Your drafts" not in body
    assert "Filter achievements" not in body
    assert "&amp;filter=unlocked" not in body
    assert badge_path(achievements["community"].badge_name) in body
    assert "_lock.png" not in body


@pytest.mark.django_db
def test_authors_drafts_are_listed_last_marked_and_out_of_the_totals(
    client, crash, achievements, player
):
    _achievement(crash, "My draft", DRAFT_POINTS, status=Achievement.STATUS_DRAFT, author=player)
    client.force_login(player)
    body = _panel(client, crash, "achievements", show="all")
    assert body.index(">Community two<") < body.index("Your drafts") < body.index(">My draft<")
    assert ">Draft</span>" in _status_badge(body, "My draft")

    page = _page(client, crash)
    assert "My draft" not in page
    # A draft is never worth points, so it stays out of the totals.
    published_points = sum(achievement.points for achievement in achievements.values())
    assert f'text-gold">{published_points}</div>' in page


# --- Achievements: status visibility ---

AUTHOR = "author"
OTHER_USER = "other"
ANONYMOUS = "anonymous"
VIEWERS = [AUTHOR, OTHER_USER, ANONYMOUS]
DRAFT_TITLE = "Author draft"


@pytest.fixture
def author(db):
    return _user("draft-author")


@pytest.fixture
def authors_draft(crash, author):
    return _achievement(crash, DRAFT_TITLE, status=Achievement.STATUS_DRAFT, author=author)


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


def _status_badge(body, title):
    """The markup of the row titled `title` after its title: its status badge."""
    row = body[body.index(f">{title}<") :]
    return row[: row.index("</div>")]


@pytest.mark.django_db
@pytest.mark.parametrize("viewer", VIEWERS)
@pytest.mark.parametrize(
    ("show", "shown", "hidden"),
    [
        ("verified", ["Verified one"], ["Community one", "Community two"]),
        ("published", ["Verified one", "Community one", "Community two"], []),
        ("all", ["Verified one", "Community one", "Community two"], []),
    ],
)
def test_show_lists_the_chosen_statuses_and_drafts_only_to_their_author(
    client, crash, achievements, authors_draft, view_as, viewer, show, shown, hidden
):
    view_as(viewer)
    body = _panel(client, crash, "achievements", show=show)
    for title in shown:
        assert f">{title}<" in body
    for title in hidden:
        assert f">{title}<" not in body
    if viewer == AUTHOR and show == "all":
        assert f">{DRAFT_TITLE}<" in body
    else:
        assert DRAFT_TITLE not in body
    if viewer == ANONYMOUS and show == "all":
        # Without drafts of their own, an anonymous visitor's "all" is the published set.
        pressed = "published"
    else:
        pressed = show
    assert f"/games/{crash.pk}/panel/achievements/?show={pressed}&" in _pressed(body, SHOW_GROUP)


@pytest.mark.django_db
@pytest.mark.parametrize("viewer", VIEWERS)
def test_page_opens_on_verified_and_community(
    client, crash, achievements, authors_draft, view_as, viewer
):
    view_as(viewer)
    body = _page(client, crash)
    assert _pressed(body, SHOW_GROUP).endswith("?show=published&amp;filter=all")
    assert ">Verified one<" in body and ">Community one<" in body
    assert DRAFT_TITLE not in body


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("viewer", "offered"),
    [(AUTHOR, ["verified", "published", "all"]), (ANONYMOUS, ["verified", "published"])],
)
def test_only_a_logged_in_viewer_is_offered_their_drafts(
    client, crash, achievements, view_as, viewer, offered
):
    view_as(viewer)
    body = _page(client, crash)
    group = body[body.index(f'aria-label="{SHOW_GROUP}"') :]
    group = group[: group.index("</div>")]
    assert group.count("<button") == len(offered)
    for slug in offered:
        assert f"?show={slug}&amp;filter=all" in group
    assert ("All incl. my drafts" in group) == ("all" in offered)


@pytest.mark.django_db
def test_published_draft_is_visible_to_everyone_and_served_as_official(
    client, admin_client, crash, authors_draft, rival, view_as
):
    for viewer in (OTHER_USER, ANONYMOUS):
        view_as(viewer)
        for show in VALID_SHOW_OPTIONS:
            assert DRAFT_TITLE not in _panel(client, crash, "achievements", show=show)

    admin_client.post(
        "/admin/achievements/achievement/",
        {"action": "publish_as_community", "_selected_action": [authors_draft.pk]},
    )

    for viewer in VIEWERS:
        view_as(viewer)
        assert ">Community</span>" in _status_badge(_page(client, crash), DRAFT_TITLE)
    data = client.post(
        "/dorequest.php",
        {"r": "achievementsets", "u": rival.username, "t": RIVAL_TOKEN, "g": crash.pk},
    ).json()
    served = {a["Title"]: a["Flags"] for a in data["Sets"][0]["Achievements"]}
    assert served == {DRAFT_TITLE: ACHIEVEMENT_FLAGS_CORE}


@pytest.mark.django_db
def test_every_achievement_carries_its_status_badge(client, crash, achievements, author):
    _achievement(crash, "My draft", status=Achievement.STATUS_DRAFT, author=author)
    client.force_login(author)
    body = _panel(client, crash, "achievements", show="all")
    verified = _status_badge(body, "Verified one")
    assert (
        "text-state-platinum" in verified and "<svg" in verified and ">Verified</span>" in verified
    )
    for title in ("Community one", "Community two"):
        assert 'text-brand">Community</span>' in _status_badge(body, title)
    assert 'text-gold">Draft</span>' in _status_badge(body, "My draft")


@pytest.mark.django_db
def test_status_badges_follow_the_viewer_language(client, crash, achievements):
    body = client.get(f"/games/{crash.pk}/", HTTP_ACCEPT_LANGUAGE="pt-br").content.decode()
    assert ">Verificado</span>" in _status_badge(body, "Verified one")
    assert "Somente verificadas" in body


@pytest.mark.django_db
def test_show_and_filter_combine_and_keep_each_other(client, crash, achievements, player):
    _unlock(player, achievements["verified"], hardcore=True)
    client.force_login(player)
    body = _panel(client, crash, "achievements", show="verified", filter="locked")
    assert "Every achievement unlocked" in body
    assert _pressed(body, SHOW_GROUP).endswith("?show=verified&amp;filter=locked")
    assert _pressed(body, FILTERS_GROUP).endswith("?show=verified&amp;filter=locked")
    assert "?show=published&amp;filter=locked" in body
    assert "?show=verified&amp;filter=unlocked" in body

    body = _panel(client, crash, "achievements", show="published", filter="locked")
    assert ">Community one<" in body and ">Verified one<" not in body


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("show", "empty_title"),
    [
        ("verified", "No verified achievements yet"),
        ("published", "No published achievements yet"),
        ("all", "No published achievements or drafts yet"),
    ],
)
@pytest.mark.parametrize("achievement_filter", VALID_FILTERS)
def test_a_status_choice_with_nothing_to_show_says_so_under_every_filter(
    client, crash, author, show, empty_title, achievement_filter
):
    if show == "verified":
        _achievement(crash, "Community only")
    client.force_login(author)
    body = _panel(client, crash, "achievements", show=show, filter=achievement_filter)
    assert empty_title in body
    assert "Every achievement unlocked" not in body


@pytest.mark.django_db
def test_unknown_status_choice_answers_400_in_the_viewer_language(client, crash):
    response = client.get(
        f"/games/{crash.pk}/panel/achievements/", {"show": "drafts"}, HTTP_ACCEPT_LANGUAGE="pt-br"
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.content.decode() == "Escolha de status de conquista desconhecida"


# --- Achievements: the viewer's unlocks ---


@pytest.mark.django_db
def test_logged_in_user_sees_hardcore_softcore_and_locked_apart(
    client, crash, achievements, player
):
    _unlock(player, achievements["verified"], hardcore=True)
    _unlock(player, achievements["community"], hardcore=False)
    client.force_login(player)
    body = _page(client, crash)

    hardcore = _row(body, "Verified one")
    assert "border-state-hardcore" in hardcore
    assert badge_path(achievements["verified"].badge_name) in hardcore

    softcore = _row(body, "Community one")
    assert "border-state-softcore" in softcore

    locked = _row(body, "Community two")
    assert badge_path(achievements["other"].badge_name, locked=True) in locked
    assert "opacity-60" in locked
    assert body.count('text-state-hardcore">') == 1
    assert body.count('text-state-softcore">') == 1


@pytest.mark.django_db
def test_hardcore_upgrade_of_a_softcore_unlock_shows_as_hardcore(
    client, crash, achievements, player
):
    earlier = timezone.now() - timedelta(days=1)
    UserUnlock.objects.create(
        user=player, achievement=achievements["community"], hardcore=False, unlocked_at=earlier
    )
    UserUnlock.objects.create(user=player, achievement=achievements["community"], hardcore=True)
    client.force_login(player)
    assert "border-state-hardcore" in _row(_page(client, crash), "Community one")


@pytest.mark.django_db
def test_another_users_unlocks_do_not_highlight_the_viewers_page(
    client, crash, achievements, player
):
    _unlock(_user("rival"), achievements["verified"], hardcore=True)
    client.force_login(player)
    body = _page(client, crash)
    assert "border-state-hardcore" not in body
    assert badge_path(achievements["verified"].badge_name, locked=True) in body


# --- Achievements: HTMX filters ---


@pytest.mark.django_db
def test_logged_in_user_gets_the_filters_with_all_active(client, crash, achievements, player):
    client.force_login(player)
    body = _page(client, crash)
    for slug in VALID_FILTERS:
        assert f'"/games/{crash.pk}/panel/achievements/?show=published&amp;filter={slug}"' in body
    assert _pressed(body, FILTERS_GROUP).endswith("filter=all")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("achievement_filter", "shown", "hidden"),
    [
        ("all", ["Verified one", "Community one", "Community two"], []),
        ("unlocked", ["Verified one", "Community one"], ["Community two"]),
        ("locked", ["Community two"], ["Verified one", "Community one"]),
    ],
)
def test_filter_returns_a_fragment_with_the_matching_achievements(
    client, crash, achievements, player, achievement_filter, shown, hidden
):
    _unlock(player, achievements["verified"], hardcore=True)
    _unlock(player, achievements["community"], hardcore=False)
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
def test_filter_applies_to_the_authors_drafts(client, crash, player):
    _achievement(crash, "My draft", status=Achievement.STATUS_DRAFT, author=player)
    client.force_login(player)
    assert ">My draft<" in _panel(client, crash, "achievements", show="all", filter="locked")
    assert ">My draft<" not in _panel(client, crash, "achievements", show="all", filter="unlocked")


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
    assert "No published achievements yet" in body
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
        ("achievements", "No published achievements yet", "Nenhuma conquista publicada ainda"),
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
    hardcore_unlocks = [achievements["verified"]]
    softcore_unlocks = [achievements["community"]]
    for achievement in hardcore_unlocks:
        _unlock(player, achievement, hardcore=True)
    for achievement in softcore_unlocks:
        _unlock(player, achievement, hardcore=False)
    _achievement(crash, "Draft", status=Achievement.STATUS_DRAFT, author=player)
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
        _achievement(crash, f"Draft {index}", status=Achievement.STATUS_DRAFT, author=player)
    assert queries() == baseline


@pytest.mark.django_db
def test_home_and_profile_link_their_games_to_the_game_page(client, crash, achievements, player):
    _unlock(player, achievements["verified"], hardcore=True)
    PlayerGame.objects.create(user=player, game=crash)
    player.softcore_points = VERIFIED_POINTS
    player.save(update_fields=["softcore_points"])
    game_link = f'href="/games/{crash.pk}/"'
    for path in ["/", "/users/teste/", "/users/teste/panel/games/", "/users/teste/panel/progress/"]:
        assert game_link in _get(client, path).content.decode(), path
