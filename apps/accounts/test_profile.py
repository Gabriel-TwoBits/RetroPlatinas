"""The profile page, its mobile panels and the edit-profile page, over real unlocks and sessions."""

import re
from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import BIO_MAX_LENGTH
from apps.accounts.profile import (
    AWARDS_SHOWN,
    HEAT_DAYS,
    LONG_WINDOW,
    RECENT_GAMES_SHOWN,
    RECENT_UNLOCKS_SHOWN,
    SHORT_WINDOW,
    VALID_TABS,
)
from apps.achievements.models import Achievement, UserUnlock
from apps.games.models import PLAYING_NOW_TTL, Console, Game, PlayerGame

User = get_user_model()

PLAYSTATION_RA_ID = 12
NINTENDO_64_RA_ID = 2
SYSTEM_ACCOUNT = "ra-import"
PASSWORD = "pw-secret-123"
TWO_HOURS_SECONDS = int(timedelta(hours=2).total_seconds())
# More unlocks than the profile lists, so the cut is visible.
EXTRA_UNLOCKS = 5
EXTRA_AWARDS = 2
# One locked achievement out of this many is 99.5% unlocked, which `round` would show as 100%.
LARGE_SET_SIZE = 200


def _user(username, hardcore_points=0, softcore_points=0, is_active=True):
    return User.objects.create_user(
        username=username,
        password=PASSWORD,
        hardcore_points=hardcore_points,
        softcore_points=softcore_points,
        is_active=is_active,
    )


def _achievement(game, title, points=5, status=Achievement.STATUS_COMMUNITY, type=""):
    return Achievement.objects.create(
        game=game,
        author=User.objects.get(username=SYSTEM_ACCOUNT),
        title=title,
        description=f"{title} description",
        points=points,
        mem_addr="0xH0001=1",
        status=status,
        type=type,
    )


def _unlock(user, achievement, hardcore, unlocked_at=None):
    """Records an unlock as `handle_awardachievement` does: hardcore writes the softcore twin."""
    unlocked_at = unlocked_at or timezone.now()
    UserUnlock.objects.create(
        user=user, achievement=achievement, hardcore=False, unlocked_at=unlocked_at
    )
    if hardcore:
        UserUnlock.objects.create(
            user=user, achievement=achievement, hardcore=True, unlocked_at=unlocked_at
        )


def _play(user, game, last_played_at=None, **fields):
    return PlayerGame.objects.create(
        user=user, game=game, last_played_at=last_played_at or timezone.now(), **fields
    )


def _get(client, path):
    return client.get(path, HTTP_ACCEPT_LANGUAGE="en")


@pytest.fixture
def playstation(db):
    _user(SYSTEM_ACCOUNT, is_active=False)
    return Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")


@pytest.fixture
def crash(playstation):
    return Game.objects.create(title="Crash Bandicoot", console=playstation)


@pytest.fixture
def player(db):
    return _user("teste")


# --- Identity: points, rank, bio, avatar ---


@pytest.mark.django_db
def test_profile_shows_points_and_rank_per_mode_without_inactive_accounts(client, playstation):
    _user("teste", hardcore_points=10, softcore_points=1500)
    _user("leader", hardcore_points=50, softcore_points=2000)
    _user("softie", hardcore_points=0, softcore_points=100)
    _user("banned", hardcore_points=999, softcore_points=9999, is_active=False)

    resp = _get(client, "/users/teste/")

    assert resp.context["ranks"] == (2, 2)
    assert resp.context["ranked_players"] == (2, 3)
    body = resp.content.decode()
    assert "1,500" in body
    assert "#2 of 2" in body
    assert "#2 of 3" in body


@pytest.mark.django_db
def test_inactive_profile_answers_without_rank(client, playstation):
    _user("banned", hardcore_points=999, softcore_points=9999, is_active=False)

    resp = _get(client, "/users/banned/")

    assert resp.status_code == HTTPStatus.OK
    assert resp.context["ranks"] == (None, None)
    assert "unranked" in resp.content.decode()


@pytest.mark.django_db
def test_profile_shows_points_grouped_in_brazilian_portuguese(client, playstation):
    _user("teste", softcore_points=1500)
    body = client.get("/users/teste/", HTTP_ACCEPT_LANGUAGE="pt-br").content.decode()
    assert "1.500" in body
    assert "#1 de 1" in body


@pytest.mark.django_db
def test_profile_uses_the_identicon_route_and_member_since(client, player):
    body = _get(client, "/users/teste/").content.decode()
    assert re.search(r'<img src="/UserPic/teste\.png\?v=[0-9a-f]+"', body)
    assert f"member since {timezone.localtime(player.date_joined):%B %Y}" in body


@pytest.mark.django_db
def test_profile_renders_the_bio_escaped(client):
    user = _user("teste")
    user.bio = "<script>alert('x')</script> retro fan"
    user.save()
    body = _get(client, "/users/teste/").content.decode()
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; retro fan" in body
    assert "<script>alert" not in body


@pytest.mark.django_db
def test_profile_404_for_missing_user(client):
    assert client.get("/users/ghost/").status_code == HTTPStatus.NOT_FOUND


# --- Empty user ---


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/users/teste/", "/users/teste/panel/progress/"])
def test_new_user_sees_empty_states_with_a_way_to_start(client, player, path):
    client.force_login(player)
    body = _get(client, path).content.decode()
    assert "No games played yet" in body
    assert "/docs/getting-started/" in body


@pytest.mark.django_db
def test_new_user_progress_panel_shows_the_empty_state_once(client, player):
    client.force_login(player)
    body = _get(client, "/users/teste/panel/progress/").content.decode()
    assert body.count("No games played yet") == 1
    assert "Progress by console" not in body


@pytest.mark.django_db
def test_new_user_profile_has_no_points_rank_or_activity(client, player):
    resp = _get(client, "/users/teste/")
    body = resp.content.decode()
    assert "unranked" in body
    assert "No unlocks yet" in body
    assert "No platinums or beaten games yet" in body
    assert "Playing now" not in body
    assert "Last played" not in body
    assert resp.context["average_completion"] is None
    assert resp.context["heat_points"] == 0
    assert not any(bar["on"] for bar in resp.context["heat"])


@pytest.mark.django_db
def test_visitor_sees_empty_states_without_the_owner_call_to_action(client, player):
    body = _get(client, "/users/teste/").content.decode()
    assert "No games played yet" in body
    assert "How to start →" not in body


# --- Recent unlocks ---


@pytest.mark.django_db
def test_profile_lists_the_last_unlocks_newest_first_once_each(client, crash, player):
    now = timezone.now()
    achievements = [
        _achievement(crash, f"Ach {index:02d}")
        for index in range(RECENT_UNLOCKS_SHOWN + EXTRA_UNLOCKS)
    ]
    for index, achievement in enumerate(achievements):
        _unlock(
            player, achievement, hardcore=index % 2 == 0, unlocked_at=now - timedelta(minutes=index)
        )

    resp = _get(client, "/users/teste/panel/overview/")

    shown = [entry["unlock"] for entry in resp.context["recent_unlocks"]]
    assert [unlock.achievement.title for unlock in shown] == [
        f"Ach {index:02d}" for index in range(RECENT_UNLOCKS_SHOWN)
    ]
    assert [unlock.hardcore for unlock in shown[:2]] == [True, False]
    body = resp.content.decode()
    titles = re.findall(r"Ach \d\d", body)
    assert titles == [f"Ach {index:02d}" for index in range(RECENT_UNLOCKS_SHOWN)]


@pytest.mark.django_db
def test_recent_unlock_badges_use_the_image_routes(client, crash, player):
    _unlock(player, _achievement(crash, "Box breaker"), hardcore=True)
    body = _get(client, "/users/teste/panel/overview/").content.decode()
    assert re.search(r'<img src="/Badge/00000\.png\?v=[0-9a-f]+"', body)
    assert "border-state-hardcore" in body


@pytest.mark.django_db
def test_recent_unlocks_leave_out_drafts(client, crash, player):
    _unlock(player, _achievement(crash, "Draft one", status=Achievement.STATUS_DRAFT), False)
    body = _get(client, "/users/teste/panel/overview/").content.decode()
    assert "Draft one" not in body
    assert "No unlocks yet" in body


# --- Games played: completion, states, playtime ---


@pytest.mark.django_db
def test_completion_counts_distinct_published_achievements_per_mode(client, crash, player):
    hardcore_one = _achievement(crash, "Hardcore one", points=10)
    softcore_one = _achievement(crash, "Softcore one", points=5)
    _achievement(crash, "Locked one", points=25)
    draft = _achievement(crash, "Draft", status=Achievement.STATUS_DRAFT)
    _unlock(player, hardcore_one, hardcore=True)
    _unlock(player, softcore_one, hardcore=False)
    _unlock(player, draft, hardcore=True)
    _play(player, crash, playtime_seconds=TWO_HOURS_SECONDS)

    resp = _get(client, "/users/teste/")

    [game] = resp.context["completion"]
    assert game["achievements"] == 3
    assert game["unlocked"] == (1, 2)
    assert game["pct"] == 66
    assert game["state"] == "progress"
    body = resp.content.decode()
    assert "PS1 · 2/3 achievements (1 hardcore) · 15/40 pts · 2 h played · now" in body
    assert "2 / 3" in body


@pytest.mark.django_db
def test_completion_reaches_100_percent_only_when_every_achievement_is_unlocked(
    client, crash, player
):
    achievements = [_achievement(crash, f"A{index}") for index in range(LARGE_SET_SIZE)]
    for achievement in achievements[1:]:
        _unlock(player, achievement, hardcore=False)
    _play(player, crash)

    [game] = _get(client, "/users/teste/").context["completion"]

    assert game["pct"] == 99
    assert game["state"] == "progress"


@pytest.mark.django_db
def test_game_states_platinum_beaten_and_in_progress(client, playstation, player):
    mastered = Game.objects.create(title="Mastered", console=playstation)
    beaten = Game.objects.create(title="Beaten", console=playstation)
    softcore_only = Game.objects.create(title="Softcore only", console=playstation)
    started = Game.objects.create(title="Started", console=playstation)
    empty = Game.objects.create(title="No set", console=playstation)

    _unlock(player, _achievement(mastered, "M1"), hardcore=True)
    _unlock(player, _achievement(mastered, "M2", type=Achievement.TYPE_WIN_CONDITION), True)
    _unlock(player, _achievement(beaten, "B1", type=Achievement.TYPE_PROGRESSION), False)
    _unlock(player, _achievement(beaten, "B2", type=Achievement.TYPE_WIN_CONDITION), True)
    _achievement(beaten, "B3")
    # Every achievement in softcore is neither platinum nor, without beating types, beaten.
    _unlock(player, _achievement(softcore_only, "S1"), hardcore=False)
    _achievement(started, "T1", type=Achievement.TYPE_WIN_CONDITION)
    for game in (mastered, beaten, softcore_only, started, empty):
        _play(player, game)

    resp = _get(client, "/users/teste/")

    states = {game["game"].title: game["state"] for game in resp.context["completion"]}
    assert states == {
        "Mastered": "platinum",
        "Beaten": "beaten",
        "Softcore only": "progress",
        "Started": "progress",
        "No set": "progress",
    }
    assert resp.context["games_beaten"] == 2
    assert resp.context["platinums"] == 1
    # Mastered, Beaten, Softcore only and Started; "No set" has no achievements to complete.
    completions = [100, 66, 100, 0]
    assert resp.context["average_completion"] == sum(completions) // len(completions)


@pytest.mark.django_db
def test_recently_played_lists_the_latest_games_first(client, playstation, player):
    now = timezone.now()
    for index in range(RECENT_GAMES_SHOWN + 1):
        game = Game.objects.create(title=f"Game {index}", console=playstation)
        _play(player, game, last_played_at=now - timedelta(days=index))

    resp = _get(client, "/users/teste/panel/games/")

    assert [game["game"].title for game in resp.context["recent_games"]] == [
        f"Game {index}" for index in range(RECENT_GAMES_SHOWN)
    ]
    assert f"Game {RECENT_GAMES_SHOWN}" not in resp.content.decode()
    assert len(resp.context["completion"]) == RECENT_GAMES_SHOWN + 1


@pytest.mark.django_db
def test_console_progression_counts_states_per_console(client, playstation, crash, player):
    nintendo = Console.objects.create(ra_id=NINTENDO_64_RA_ID, name="Nintendo 64", short_name="N64")
    kart = Game.objects.create(title="Kart", console=nintendo)
    _unlock(player, _achievement(kart, "K1"), hardcore=True)
    _achievement(crash, "C1")
    _play(player, crash)
    _play(player, kart)

    resp = _get(client, "/users/teste/panel/progress/")

    rows = [
        (row["tag"], row["total"], row["not_done"], row["beaten"], row["plat"])
        for row in resp.context["consoles"]
    ]
    assert rows == [("∑", 2, 1, 0, 1), ("N64", 1, 0, 0, 1), ("PS1", 1, 1, 0, 0)]
    assert resp.context["consoles"][0]["plat_pct"] == "50.0%"
    assert "Nintendo 64" in resp.content.decode()


@pytest.mark.django_db
def test_awards_list_platinums_before_beaten_games(client, playstation, player):
    now = timezone.now()
    beaten = Game.objects.create(title="Beaten game", console=playstation)
    mastered = Game.objects.create(title="Mastered game", console=playstation)
    _unlock(player, _achievement(beaten, "B1", type=Achievement.TYPE_WIN_CONDITION), False)
    _unlock(player, _achievement(mastered, "M1"), hardcore=True)
    _play(player, beaten, last_played_at=now)
    _play(player, mastered, last_played_at=now - timedelta(days=1))

    body = _get(client, "/users/teste/panel/awards/").content.decode()

    tones = re.findall(r'class="text-(state-platinum|state-beaten) rp-hatch', body)
    assert tones == ["state-platinum", "state-beaten"]


@pytest.mark.django_db
def test_awards_cut_at_the_shown_count(client, playstation, player):
    for index in range(AWARDS_SHOWN + EXTRA_AWARDS):
        game = Game.objects.create(title=f"Game {index}", console=playstation)
        _unlock(player, _achievement(game, f"A{index}"), hardcore=True)
        _play(player, game)

    resp = _get(client, "/users/teste/")

    assert len(resp.context["awards"]) == AWARDS_SHOWN
    assert resp.context["awards_more"] == EXTRA_AWARDS
    assert f"+{EXTRA_AWARDS}</div>" in resp.content.decode()


# --- Activity: windows and heat ---


@pytest.mark.django_db
def test_points_windows_and_heat_count_each_achievement_once(client, crash, player):
    now = timezone.now()
    _unlock(player, _achievement(crash, "Today", points=10), hardcore=True, unlocked_at=now)
    _unlock(player, _achievement(crash, "Ten days", points=5), False, now - timedelta(days=10))
    _unlock(player, _achievement(crash, "Twenty days", points=7), False, now - timedelta(days=20))
    _unlock(player, _achievement(crash, "Old", points=50), False, now - timedelta(days=60))

    resp = _get(client, "/users/teste/panel/overview/")

    assert resp.context["points_short_window"] == (10, 10)
    assert resp.context["points_long_window"] == (10, 22)
    assert resp.context["heat_points"] == 15
    heat = resp.context["heat"]
    assert heat[-1]["on"] and heat[-1]["opacity"] == "1.00"
    assert [bar["on"] for bar in heat].count(True) == 2
    assert "15 pts" in resp.content.decode()


@pytest.mark.django_db
def test_points_windows_split_by_mode(client, crash, player):
    now = timezone.now()
    upgraded = _achievement(crash, "Upgraded", points=3)
    # Softcore first, hardcore later: each mode counts the achievement when it reached that mode.
    _unlock(player, upgraded, hardcore=False, unlocked_at=now - timedelta(days=20))
    UserUnlock.objects.create(
        user=player, achievement=upgraded, hardcore=True, unlocked_at=now - timedelta(days=2)
    )
    _unlock(player, _achievement(crash, "Hardcore", points=4), True, now - timedelta(days=12))
    _unlock(player, _achievement(crash, "Softcore", points=5), False, now - timedelta(days=1))

    resp = _get(client, "/users/teste/")

    assert resp.context["points_short_window"] == (3, 5)
    assert resp.context["points_long_window"] == (7, 12)
    stats_section = resp.content.decode().split("Player statistics", 1)[1]
    for label, value in (
        (f"Hardcore points ({SHORT_WINDOW.days} days)", 3),
        (f"Softcore points ({SHORT_WINDOW.days} days)", 5),
        (f"Hardcore points ({LONG_WINDOW.days} days)", 7),
        (f"Softcore points ({LONG_WINDOW.days} days)", 12),
    ):
        assert re.search(rf"{re.escape(label)}</div>.*?>{value}</span>", stats_section, re.S)


@pytest.mark.django_db
def test_points_per_week_split_by_mode(client, playstation):
    user = _user("teste", hardcore_points=30, softcore_points=90)
    User.objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(weeks=3))

    resp = _get(client, "/users/teste/")

    assert resp.context["points_per_week"] == (10, 30)
    body = resp.content.decode()
    assert re.search(r"Hardcore points per week</div>.*?>10</span>", body, re.S)
    assert re.search(r"Softcore points per week</div>.*?>30</span>", body, re.S)


@pytest.mark.django_db
def test_new_user_points_per_week_count_at_least_one_week(client, playstation):
    _user("teste", hardcore_points=4, softcore_points=8)
    assert _get(client, "/users/teste/").context["points_per_week"] == (4, 8)


# --- Playing now ---


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("language", "window_label", "heat_label"),
    [
        ("en", "Softcore points ({} days)", "{}d ago"),
        ("pt-br", "Pontos softcore ({} dias)", "há {} dias"),
    ],
)
@pytest.mark.parametrize("path", ["/users/teste/", "/users/teste/panel/overview/"])
def test_window_and_heat_labels_follow_their_spans(
    client, player, path, language, window_label, heat_label
):
    body = client.get(path, HTTP_ACCEPT_LANGUAGE=language).content.decode()
    assert window_label.format(SHORT_WINDOW.days) in body
    assert window_label.format(LONG_WINDOW.days) in body
    # The oldest bar is `HEAT_DAYS - 1` days before today's.
    assert heat_label.format(HEAT_DAYS - 1) in body


@pytest.mark.django_db
def test_live_session_shows_playing_now_with_rich_presence(client, crash, player):
    _play(
        player,
        crash,
        last_ping_at=timezone.now(),
        last_rich_presence="Level 3, 2 lives",
        hardcore=True,
    )
    body = _get(client, "/users/teste/").content.decode()
    assert "Playing now" in body
    assert "Level 3, 2 lives" in body


@pytest.mark.django_db
def test_stale_session_shows_last_played_without_rich_presence(client, crash, player):
    stale = timezone.now() - PLAYING_NOW_TTL - timedelta(minutes=1)
    _play(player, crash, last_played_at=stale, last_ping_at=stale, last_rich_presence="Level 3")
    body = _get(client, "/users/teste/").content.decode()
    assert "Playing now" not in body
    assert "Last played" in body
    assert "Level 3" not in body


# --- Owner vs visitor, edit profile ---


@pytest.mark.django_db
def test_edit_profile_button_only_for_the_owner(client, player):
    other = _user("other")
    assert "Edit profile" not in _get(client, "/users/teste/").content.decode()
    client.force_login(other)
    assert "Edit profile" not in _get(client, "/users/teste/").content.decode()
    client.force_login(player)
    assert 'href="/users/teste/edit/"' in _get(client, "/users/teste/").content.decode()


@pytest.mark.django_db
def test_edit_profile_redirects_an_anonymous_user_to_login(client, player):
    for resp in (client.get("/users/teste/edit/"), client.post("/users/teste/edit/", {})):
        assert resp.status_code == HTTPStatus.FOUND
        assert resp.url == "/login/?next=/users/teste/edit/"


@pytest.mark.django_db
def test_edit_profile_forbids_another_user(client, player):
    client.force_login(_user("other"))
    assert client.get("/users/teste/edit/").status_code == HTTPStatus.FORBIDDEN
    resp = client.post("/users/teste/edit/", {"bio": "hijacked"})
    assert resp.status_code == HTTPStatus.FORBIDDEN
    player.refresh_from_db()
    assert player.bio == ""


@pytest.mark.django_db
def test_edit_profile_404_for_missing_user(client, player):
    client.force_login(player)
    assert client.get("/users/ghost/edit/").status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_owner_edits_the_bio(client, player):
    client.force_login(player)
    assert "Edit profile" in _get(client, "/users/teste/edit/").content.decode()

    resp = client.post("/users/teste/edit/", {"bio": "Platinum hunter."})

    assert resp.status_code == HTTPStatus.FOUND
    assert resp.url == "/users/teste/"
    player.refresh_from_db()
    assert player.bio == "Platinum hunter."
    assert "Platinum hunter." in _get(client, "/users/teste/").content.decode()


@pytest.mark.django_db
def test_saving_the_bio_writes_no_other_column(client, player):
    client.force_login(player)
    with CaptureQueriesContext(connection) as queries:
        client.post("/users/teste/edit/", {"bio": "Platinum hunter."})
    updates = [q["sql"] for q in queries if q["sql"].startswith('UPDATE "accounts_user"')]
    assert len(updates) == 1
    assert '"bio"' in updates[0]
    assert "points" not in updates[0]
    assert "api_token" not in updates[0]


@pytest.mark.django_db
def test_owner_clears_the_bio(client, player):
    player.bio = "Old bio"
    player.save()
    client.force_login(player)
    client.post("/users/teste/edit/", {"bio": ""})
    player.refresh_from_db()
    assert player.bio == ""


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("language", "help_text"),
    [
        ("en", "up to {} characters"),
        ("pt-br", "com até {} caracteres"),
    ],
)
def test_edit_profile_states_and_enforces_the_bio_limit(client, player, language, help_text):
    client.force_login(player)
    body = client.get("/users/teste/edit/", HTTP_ACCEPT_LANGUAGE=language).content.decode()
    assert help_text.format(BIO_MAX_LENGTH) in body
    assert f'maxlength="{BIO_MAX_LENGTH}"' in body


@pytest.mark.django_db
def test_edit_profile_accepts_a_bio_at_the_limit(client, player):
    client.force_login(player)
    resp = client.post("/users/teste/edit/", {"bio": "x" * BIO_MAX_LENGTH})
    assert resp.status_code == HTTPStatus.FOUND
    player.refresh_from_db()
    assert player.bio == "x" * BIO_MAX_LENGTH


@pytest.mark.django_db
def test_edit_profile_counts_a_line_break_as_one_character(client, player):
    client.force_login(player)
    head = "x" * (BIO_MAX_LENGTH - len("\n\nx"))
    resp = client.post("/users/teste/edit/", {"bio": f"{head}\r\n\r\nx"})
    assert resp.status_code == HTTPStatus.FOUND
    player.refresh_from_db()
    assert player.bio == f"{head}\n\nx"


@pytest.mark.django_db
def test_edit_profile_rejects_a_bio_over_the_limit(client, player):
    client.force_login(player)
    resp = client.post(
        "/users/teste/edit/", {"bio": "x" * (BIO_MAX_LENGTH + 1)}, HTTP_ACCEPT_LANGUAGE="en"
    )
    assert resp.status_code == HTTPStatus.OK
    assert "Ensure this value has at most" in resp.content.decode()
    player.refresh_from_db()
    assert player.bio == ""


# --- Panels and page structure ---


@pytest.mark.django_db
def test_profile_panel_returns_a_fragment(client, crash, player):
    _play(player, crash)
    resp = _get(client, "/users/teste/panel/progress/")
    assert resp.status_code == HTTPStatus.OK
    body = resp.content.decode()
    assert "<!DOCTYPE" not in body
    assert "PlayStation" in body


@pytest.mark.django_db
@pytest.mark.parametrize("tab", ["wall", "bogus"])
def test_profile_panel_rejects_an_unknown_tab(client, player, tab):
    assert client.get(f"/users/teste/panel/{tab}/").status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("tab", "english", "portuguese"),
    [
        ("overview", "Recent progress", "Progresso recente"),
        ("awards", "game awards", "prêmios de jogo"),
        ("games", "Recently played", "Jogados recentemente"),
        ("progress", "No games played yet", "Nenhum jogo jogado ainda"),
    ],
)
@pytest.mark.parametrize("language", ["en", "pt-br"])
def test_profile_panels_render_in_each_language(client, player, tab, english, portuguese, language):
    resp = client.get(f"/users/teste/panel/{tab}/", HTTP_ACCEPT_LANGUAGE=language)
    assert resp.status_code == HTTPStatus.OK
    assert resp.headers["Content-Language"] == language
    if language == "en":
        assert english in resp.content.decode()
    else:
        assert portuguese in resp.content.decode()


@pytest.mark.django_db
def test_mobile_profile_tabs_put_awards_right_after_overview(client, player):
    body = client.get("/users/teste/").content.decode()
    assert re.findall(r"/users/teste/panel/(\w+)/", body) == VALID_TABS


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path", ["/users/teste/", *(f"/users/teste/panel/{tab}/" for tab in VALID_TABS)]
)
def test_profile_hides_sections_without_a_concept_and_dead_links(client, crash, player, path):
    _unlock(player, _achievement(crash, "C1"), hardcore=True)
    _play(player, crash)
    client.force_login(player)
    body = _get(client, path).content.decode()
    for hidden in [
        "Event awards",
        "User wall",
        "RetroRatio",
        "Forum posts",
        "weighted",
        "Sets requested",
        "retail",
        "more games",
        'href="#"',
    ]:
        assert hidden not in body


@pytest.mark.django_db
def test_profile_query_count_does_not_grow_with_games_and_unlocks(client, playstation, player):
    def queries():
        with CaptureQueriesContext(connection) as captured:
            assert _get(client, "/users/teste/").status_code == HTTPStatus.OK
        return len(captured)

    first = Game.objects.create(title="First", console=playstation)
    _unlock(player, _achievement(first, "F1"), hardcore=True)
    _play(player, first)
    baseline = queries()

    for index in range(3):
        game = Game.objects.create(title=f"More {index}", console=playstation)
        _unlock(player, _achievement(game, f"M{index}", type=Achievement.TYPE_WIN_CONDITION), False)
        _play(player, game)

    assert queries() == baseline
