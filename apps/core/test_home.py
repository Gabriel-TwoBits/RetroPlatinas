"""The home page over real sets, unlocks and live sessions."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.achievements.models import Achievement, UserUnlock
from apps.core.home import PLAYING_NOW_SHOWN, RECENT_ACTIVITY_SHOWN
from apps.games.models import PLAYING_NOW_TTL, Console, Game, PlayerGame
from apps.images.catalog import badge_path, versioned_game_icon_path

User = get_user_model()

PLAYSTATION_RA_ID = 12
NINTENDO_64_RA_ID = 2
SYSTEM_ACCOUNT = "ra-import"
PASSWORD = "pw-secret-123"
# More rows than the home lists, so the cut is visible.
EXTRA_ROWS = 3
LARGE_POINTS = 1500


def _user(username, hardcore_points=0, softcore_points=0, is_active=True):
    return User.objects.create_user(
        username=username,
        password=PASSWORD,
        hardcore_points=hardcore_points,
        softcore_points=softcore_points,
        is_active=is_active,
    )


def _achievement(game, title, points=5, status=Achievement.STATUS_OFFICIAL):
    return Achievement.objects.create(
        game=game,
        author=User.objects.get(username=SYSTEM_ACCOUNT),
        title=title,
        description=f"{title} description",
        points=points,
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


def _live(user, game, rich_presence="", hardcore=False, pinged_ago=timedelta(0)):
    pinged_at = timezone.now() - pinged_ago
    return PlayerGame.objects.create(
        user=user,
        game=game,
        last_played_at=pinged_at,
        last_ping_at=pinged_at,
        session_started_at=pinged_at,
        last_rich_presence=rich_presence,
        hardcore=hardcore,
    )


def _get(client, language="en"):
    return client.get("/", HTTP_ACCEPT_LANGUAGE=language)


def _section(body, heading):
    start = body.index(heading)
    return body[start : body.index("</section>", start)]


@pytest.fixture
def playstation(db):
    _user(SYSTEM_ACCOUNT, is_active=False)
    return Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")


@pytest.fixture
def crash(playstation):
    return Game.objects.create(title="Crash Bandicoot", console=playstation)


@pytest.fixture
def player(db):
    return _user("teste", softcore_points=5)


# --- Numbers ---


@pytest.mark.django_db
def test_numbers_count_only_official_sets_and_active_scoring_players(client, crash):
    unofficial_only = Game.objects.create(title="Spyro", console=crash.console)
    Game.objects.create(title="Ape Escape", console=crash.console)
    beach = _achievement(crash, "N. Sanity Beach")
    _achievement(crash, "Jungle Rollers", status=Achievement.STATUS_OFFICIAL)
    unofficial = _achievement(crash, "Unofficial", status=Achievement.STATUS_UNOFFICIAL)
    _achievement(unofficial_only, "Spyro unofficial", status=Achievement.STATUS_UNOFFICIAL)
    scorer = _user("scorer", hardcore_points=5, softcore_points=5)
    _user("softie", softcore_points=5)
    _user("idle")
    banned = _user("banned", softcore_points=999, is_active=False)
    _unlock(scorer, beach, hardcore=True)
    _unlock(scorer, unofficial, hardcore=False)
    _unlock(banned, beach, hardcore=False)

    numbers = _get(client).context["numbers"]

    assert numbers == {"games": 1, "achievements": 2, "players": 2, "unlocks": 1}


@pytest.mark.django_db
def test_unlocks_count_a_hardcore_upgrade_of_an_earlier_softcore_unlock_apart(client, crash):
    beach = _achievement(crash, "N. Sanity Beach")
    rollers = _achievement(crash, "Jungle Rollers")
    scorer = _user("scorer", softcore_points=10)
    _unlock(scorer, beach, hardcore=False, unlocked_at=timezone.now() - timedelta(days=1))
    _unlock(scorer, beach, hardcore=True)
    _unlock(scorer, rollers, hardcore=True)

    assert _get(client).context["numbers"]["unlocks"] == 3


@pytest.mark.django_db
def test_numbers_show_zero_on_an_empty_site(client):
    resp = _get(client)

    assert resp.context["numbers"] == {"games": 0, "achievements": 0, "players": 0, "unlocks": 0}
    assert "Online now" not in resp.content.decode()


# --- Available sets ---


@pytest.mark.django_db
def test_sets_list_official_games_with_icon_link_and_counts(client, crash):
    beach = _achievement(crash, "N. Sanity Beach", points=LARGE_POINTS)
    rollers = _achievement(crash, "Jungle Rollers", points=10, status=Achievement.STATUS_OFFICIAL)
    _achievement(crash, "Unofficial", points=50, status=Achievement.STATUS_UNOFFICIAL)
    for username in ("one", "two"):
        scorer = _user(username, softcore_points=LARGE_POINTS)
        _unlock(scorer, beach, hardcore=True)
        _unlock(scorer, rollers, hardcore=False)

    resp = _get(client)

    [crash_set] = resp.context["sets"]
    assert (crash_set["achievements"], crash_set["points"], crash_set["players"]) == (
        2,
        LARGE_POINTS + 10,
        2,
    )
    section = _section(resp.content.decode(), "Available sets")
    assert f'href="/games/{crash.pk}/"' in section
    assert f'src="{versioned_game_icon_path(crash)}"' in section
    assert "Crash Bandicoot" in section
    assert ">PS1<" in section
    assert "2 achievements" in section
    assert "1,510 pts" in section
    assert "2 players" in section
    assert "First set: Crash Bandicoot (PS1)" in resp.content.decode()


@pytest.mark.django_db
def test_sets_leave_out_games_without_official_achievements(client, crash):
    _achievement(crash, "N. Sanity Beach")
    spyro = Game.objects.create(title="Spyro", console=crash.console)
    _achievement(spyro, "Unofficial", status=Achievement.STATUS_UNOFFICIAL)
    Game.objects.create(title="Ape Escape", console=crash.console)

    resp = _get(client)

    assert [item["game"] for item in resp.context["sets"]] == [crash]
    section = _section(resp.content.decode(), "Available sets")
    assert "Spyro" not in section
    assert "Ape Escape" not in section


@pytest.mark.django_db
def test_sets_are_ordered_by_title_across_consoles(client, crash):
    nintendo_64 = Console.objects.create(
        ra_id=NINTENDO_64_RA_ID, name="Nintendo 64", short_name="N64"
    )
    banjo = Game.objects.create(title="Banjo-Kazooie", console=nintendo_64)
    for game in (crash, banjo):
        _achievement(game, f"{game.title} first")

    assert [item["game"] for item in _get(client).context["sets"]] == [banjo, crash]


@pytest.mark.django_db
def test_set_players_are_the_scoring_players_the_numbers_count(client, crash):
    beach = _achievement(crash, "N. Sanity Beach")
    unofficial = _achievement(crash, "Unofficial", status=Achievement.STATUS_UNOFFICIAL)
    scorer = _user("scorer", softcore_points=5)
    _unlock(scorer, beach, hardcore=False)
    _live(scorer, crash)
    _live(_user("idle"), crash)
    _unlock(_user("unofficial-player", softcore_points=5), unofficial, hardcore=False)
    _unlock(_user("banned", softcore_points=5, is_active=False), beach, hardcore=False)

    resp = _get(client)

    [crash_set] = resp.context["sets"]
    assert crash_set["players"] == 1


@pytest.mark.django_db
def test_sets_use_singular_labels_for_one(client, crash):
    beach = _achievement(crash, "N. Sanity Beach", points=1)
    _unlock(_user("one", softcore_points=1), beach, hardcore=False)

    section = _section(_get(client).content.decode(), "Available sets")

    assert "1 achievement\n" in section
    assert "1 pt\n" in section
    assert "1 player\n" in section


@pytest.mark.django_db
def test_sets_show_an_honest_empty_state_without_official_games(client, crash):
    _achievement(crash, "Unofficial", status=Achievement.STATUS_UNOFFICIAL)

    body = _get(client).content.decode()

    section = _section(body, "Available sets")
    assert "No official sets yet" in section
    assert "/games/" not in section
    assert "First set" not in body


# --- Recent activity ---


@pytest.mark.django_db
def test_activity_lists_unlocks_newest_first_once_each(client, crash, player):
    now = timezone.now()
    beach = _achievement(crash, "N. Sanity Beach")
    rollers = _achievement(crash, "Jungle Rollers")
    _unlock(player, beach, hardcore=True, unlocked_at=now - timedelta(hours=2))
    _unlock(player, rollers, hardcore=False, unlocked_at=now - timedelta(minutes=5))

    resp = _get(client)

    activity = [(a["unlock"].achievement, a["unlock"].hardcore) for a in resp.context["activity"]]
    assert activity == [(rollers, False), (beach, True)]
    section = _section(resp.content.decode(), "Recent activity")
    assert section.index("Jungle Rollers") < section.index("N. Sanity Beach")
    assert section.count('href="/users/teste/"') == len(activity)
    assert f'src="{badge_path(beach.badge_name)}"' in section
    assert "2\xa0hours ago" in section
    assert section.count(">HC<") == 1


@pytest.mark.django_db
def test_activity_leaves_out_unofficial_achievements_and_inactive_users(client, crash, player):
    unofficial = _achievement(crash, "Secret unofficial", status=Achievement.STATUS_UNOFFICIAL)
    beach = _achievement(crash, "N. Sanity Beach")
    _unlock(player, unofficial, hardcore=False)
    _unlock(_user("banned", is_active=False), beach, hardcore=True)

    resp = _get(client)

    assert resp.context["activity"] == []
    section = _section(resp.content.decode(), "Recent activity")
    assert "Secret unofficial" not in section
    assert "banned" not in section


@pytest.mark.django_db
def test_activity_shows_only_the_latest_unlocks(client, crash, player):
    now = timezone.now()
    achievements = [
        _achievement(crash, f"Achievement {index}")
        for index in range(RECENT_ACTIVITY_SHOWN + EXTRA_ROWS)
    ]
    for minutes_ago, achievement in enumerate(achievements):
        _unlock(
            player, achievement, hardcore=False, unlocked_at=now - timedelta(minutes=minutes_ago)
        )

    activity = _get(client).context["activity"]

    assert [a["unlock"].achievement for a in activity] == achievements[:RECENT_ACTIVITY_SHOWN]


@pytest.mark.django_db
def test_activity_shows_an_honest_empty_state_linking_the_guide(client, crash):
    section = _section(_get(client).content.decode(), "Recent activity")

    assert "No unlocks yet" in section
    assert 'href="/docs/getting-started/"' in section
    assert "real time" not in section


# --- Playing now ---


@pytest.mark.django_db
def test_playing_now_lists_live_sessions_of_active_users(client, crash, player):
    _live(player, crash, rich_presence="Level 3, 2 lives", hardcore=True)
    stale = Game.objects.create(title="Spyro", console=crash.console)
    _live(_user("gone"), stale, pinged_ago=PLAYING_NOW_TTL + timedelta(minutes=1))
    _live(_user("banned", is_active=False), crash)

    resp = _get(client)

    assert [p["played"].user for p in resp.context["playing_now"]["sessions"]] == [player]
    section = _section(resp.content.decode(), "Playing now")
    assert 'href="/users/teste/"' in section
    assert 'src="/UserPic/teste.png?v=' in section
    assert "Level 3, 2 lives" in section
    assert "hardcore" in section
    assert "Spyro" not in section
    assert "playing in all" not in section


@pytest.mark.django_db
def test_playing_now_is_hidden_when_nobody_plays(client, crash, player):
    _live(player, crash, pinged_ago=PLAYING_NOW_TTL + timedelta(minutes=1))

    resp = _get(client)

    assert resp.context["playing_now"]["total"] == 0
    assert "Playing now" not in resp.content.decode()


@pytest.mark.django_db
def test_playing_now_shows_the_total_beyond_the_listed_sessions(client, crash):
    total = PLAYING_NOW_SHOWN + EXTRA_ROWS
    for index in range(total):
        _live(_user(f"player{index}"), crash, pinged_ago=timedelta(seconds=index))

    resp = _get(client)

    sessions = resp.context["playing_now"]["sessions"]
    assert len(sessions) == PLAYING_NOW_SHOWN
    assert sessions[0]["played"].user.username == "player0"
    assert f"{total} playing in all" in _section(resp.content.decode(), "Playing now")


# --- Whole page ---


@pytest.mark.django_db
def test_home_queries_do_not_grow_with_rows(client, crash):
    def query_count():
        with CaptureQueriesContext(connection) as queries:
            _get(client)
        return len(queries)

    beach = _achievement(crash, "N. Sanity Beach")
    first = _user("first", softcore_points=5)
    _unlock(first, beach, hardcore=True)
    _live(first, crash)
    baseline = query_count()

    nintendo_64 = Console.objects.create(
        ra_id=NINTENDO_64_RA_ID, name="Nintendo 64", short_name="N64"
    )
    for index in range(EXTRA_ROWS):
        game = Game.objects.create(title=f"Game {index}", console=nintendo_64)
        achievement = _achievement(game, f"Achievement {index}")
        other = _user(f"other{index}", softcore_points=5)
        _unlock(other, achievement, hardcore=True)
        _live(other, game)

    assert query_count() == baseline


@pytest.mark.django_db
def test_home_is_translated_to_brazilian_portuguese(client, crash, player):
    beach = _achievement(crash, "N. Sanity Beach", points=10)
    _unlock(player, beach, hardcore=False)
    _live(player, crash)

    body = _get(client, "pt-br").content.decode()

    assert "1 conquista\n" in body
    assert "10 pts\n" in body
    assert "1 jogador\n" in body
    assert "desbloqueou" in body
    assert "Jogando agora" in body
    assert "cada número desta página é real" in body


@pytest.mark.django_db
def test_home_empty_states_are_translated_to_brazilian_portuguese(client):
    body = _get(client, "pt-br").content.decode()

    assert "Nenhum set oficial ainda" in body
    assert "Nenhum desbloqueio ainda" in body


# --- Purpose copy ---


def _hero(body):
    return body[body.index("<section") : body.index("</section>")]


@pytest.mark.django_db
def test_hero_says_the_core_set_is_the_normal_100_and_challenges_are_opt_in(client):
    body = _get(client).content.decode()

    assert "<title>RetroPlatinas — retro achievement sets anyone can start</title>" in body
    hero = _hero(body)
    assert "Retro achievement sets anyone can start." in hero
    assert "core set is its normal 100%" in hero
    assert "without walls of missables and grinds" in hero
    assert "Each one stays off until you turn it on." in hero


@pytest.mark.django_db
def test_hero_is_translated_to_brazilian_portuguese(client):
    body = _get(client, "pt-br").content.decode()

    title = "RetroPlatinas — sets de conquistas retrô que qualquer um pode começar"
    assert f"<title>{title}</title>" in body
    hero = _hero(body)
    assert "Sets de conquistas retrô que qualquer um pode começar." in hero
    assert "o 100% normal dele" in hero
    assert "Cada um fica desligado até você ligar." in hero


@pytest.mark.django_db
def test_home_describes_the_purpose_to_search_engines(client):
    body = _get(client).content.decode()

    assert '<meta name="description" content="Retro achievement sets anyone can start:' in body


@pytest.mark.django_db
def test_home_describes_the_purpose_to_search_engines_in_brazilian_portuguese(client):
    body = _get(client, "pt-br").content.decode()

    assert '<meta name="description" content="Sets de conquistas retrô que qualquer um' in body


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("language", "heading", "item", "detail"),
    [
        (
            "en",
            "What's new",
            "Core set and opt-in subsets",
            "The platinum is the core set in hardcore.",
        ),
        (
            "pt-br",
            "Novidades",
            "Set principal e subsets opcionais",
            "O platinado é o set principal em hardcore.",
        ),
    ],
)
def test_whats_new_announces_the_core_set_and_opt_in_subsets(
    client, language, heading, item, detail
):
    section = _section(_get(client, language).content.decode(), heading)

    assert item in section
    assert detail in section


@pytest.mark.django_db
def test_how_to_contribute_points_writers_to_the_set_guidance(client):
    section = _section(_get(client).content.decode(), "How to contribute")

    assert "Write achievements" in section
    assert "the challenges in a subset" in section
    assert 'href="/docs/creating-achievements/"' in section
    assert "No gatekeeping" not in section


@pytest.mark.django_db
def test_how_to_start_says_subsets_wait_for_the_player(client):
    section = _section(_get(client).content.decode(), "How to start playing")

    assert "The core set loads on its own. Subsets wait until you turn them on." in section
