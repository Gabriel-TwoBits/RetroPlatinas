import re
import subprocess
from datetime import timedelta
from http import HTTPStatus
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission
from django.core.management import CommandError, call_command
from django.db import IntegrityError
from django.utils import timezone

from apps.accounts.models import User
from apps.achievements.management.commands import seed_crash1_code_notes as seed_code_notes
from apps.achievements.management.commands.seed_crash1_advanced_achievements import (
    BOSS_POINTS,
    BOSS_TITLE,
    GEM_ACHIEVEMENTS,
    PAPU_PAPU_LEVEL_ID,
    advanced_achievements,
    build_boss_mem_addr,
    build_gem_mem_addr,
    gem_bit,
)
from apps.achievements.management.commands.seed_crash1_code_notes import load_code_notes
from apps.achievements.management.commands.seed_crash1_collectible_achievements import (
    AKU_TITLE,
    CHALLENGE_POINTS,
    LIVES_TITLE,
    NO_WUMPA_TITLE,
    WUMPA_POINTS,
    WUMPA_TITLE,
    build_aku_mem_addr,
    build_lives_mem_addr,
    build_no_wumpa_mem_addr,
    build_wumpa_mem_addr,
    collectible_achievements,
    in_play,
)
from apps.achievements.management.commands.seed_crash1_leaderboards import (
    INTRO,
    LEADERBOARD_FORMAT,
    SPIN_IN,
    build_leaderboard_mem,
    build_start,
    leaderboards,
)
from apps.achievements.management.commands.seed_crash1_level_achievements import (
    ACHIEVEMENT_POINTS,
    LEVEL_ACHIEVEMENTS,
    build_description,
    build_mem_addr,
)
from apps.achievements.management.commands.seed_crash1_rich_presence import build_rich_presence
from apps.achievements.management.crash1 import (
    GAME_TITLE,
    IMPORT_AUTHOR,
    PS1_RA_ID,
    USA_DISC_LABEL,
    USA_DISC_MD5,
)
from apps.achievements.models import Achievement, CodeNote, UserUnlock
from apps.anticheat.detection import award_validation_hash
from apps.api.handlers import ACHIEVEMENT_FLAGS_CORE
from apps.games.models import Console, Game, GameHash, PlayerGame
from apps.leaderboards.models import Leaderboard, LeaderboardEntry

MEM_ADDR_PATTERN = re.compile(
    r"^d0xH6188d=h(?P<level_id>[0-9a-f]{2})S0xH6188d=h2dS0xH6188d=h19_0xH618d1=3$"
)
HEX = 16
LEVEL_COUNT = len(LEVEL_ACHIEVEMENTS)
CODE_NOTE_COUNT = 113
EDITED_POINTS = 10
SEED_COMMANDS = (
    "seed_crash1_code_notes",
    "seed_crash1_level_achievements",
    "seed_crash1_collectible_achievements",
    "seed_crash1_advanced_achievements",
    "seed_crash1_rich_presence",
    "seed_crash1_leaderboards",
)
COLLECTIBLE_COUNT = len(collectible_achievements())
COLLECTIBLE_POINTS = {
    WUMPA_TITLE: WUMPA_POINTS,
    AKU_TITLE: CHALLENGE_POINTS,
    LIVES_TITLE: CHALLENGE_POINTS,
    NO_WUMPA_TITLE: CHALLENGE_POINTS,
}
EDITED_COLLECTIBLE_POINTS = 15  # no collectible achievement is seeded with this value
ADVANCED_COUNT = len(advanced_achievements())
ADVANCED_POINTS = {
    **{title: points for title, _stage, _map_index, points in GEM_ACHIEVEMENTS},
    BOSS_TITLE: BOSS_POINTS,
}
EDITED_ADVANCED_POINTS = 50  # no advanced achievement is seeded with this value
# Map cursor `0x619c5` of the first stage whose gem bit sits in the second byte (bit 8).
HOG_WILD_MAP_INDEX = 0x07
NSANITY_BEACH_LEVEL_ID = dict(LEVEL_ACHIEVEMENTS)["N. Sanity Beach"]
MAX_RICH_PRESENCE_SCRIPT_BYTES = 65535  # the RetroAchievements limit on a script
MEM_ADDR_CHECKER = Path(__file__).resolve().parents[2] / "scripts" / "check-mem-addr.sh"


def run_mem_addr_checker(*mem_addrs):
    return subprocess.run(
        ["bash", str(MEM_ADDR_CHECKER), *mem_addrs],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def user():
    return User.objects.create_user(username="player", password="pw-test-123")


@pytest.fixture
def game():
    console = Console.objects.create(ra_id=12, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


@pytest.fixture
def achievement(game, user):
    return Achievement.objects.create(
        game=game,
        author=user,
        title="First Steps",
        description="Complete N. Sanity Beach",
        points=5,
        mem_addr="0xH001234=5",
        status=Achievement.STATUS_DRAFT,
    )


@pytest.mark.django_db
def test_achievement_creation(achievement):
    assert achievement.status == Achievement.STATUS_DRAFT
    assert "First Steps" in str(achievement)


@pytest.mark.django_db
def test_achievement_type_defaults_to_none(achievement):
    achievement.refresh_from_db()
    assert achievement.type == Achievement.TYPE_NONE


@pytest.mark.django_db
def test_achievement_status_choices():
    values = [c[0] for c in Achievement.STATUS_CHOICES]
    assert Achievement.STATUS_DRAFT in values
    assert Achievement.STATUS_COMMUNITY in values
    assert Achievement.STATUS_VERIFIED in values


@pytest.mark.django_db
def test_userunlock_creation(achievement, user):
    unlock = UserUnlock.objects.create(user=user, achievement=achievement, hardcore=False)
    assert not unlock.hardcore


@pytest.mark.django_db
def test_userunlock_unique_together(achievement, user):
    UserUnlock.objects.create(user=user, achievement=achievement, hardcore=False)
    with pytest.raises(IntegrityError):
        UserUnlock.objects.create(user=user, achievement=achievement, hardcore=False)


@pytest.mark.django_db
def test_codenote_creation(game, user):
    note = CodeNote.objects.create(game=game, author=user, address="0x001234", note="lives counter")
    assert str(note) == f"0x001234 ({game})"


@pytest.mark.django_db
def test_seed_crash1_code_notes_command():
    call_command("seed_crash1_code_notes", verbosity=0)
    notes = CodeNote.objects.filter(game__title="Crash Bandicoot")
    assert notes.count() == CODE_NOTE_COUNT
    assert "N. Sanity Beach" in notes.get(address="0x619c5").note
    assert "Overworld" in notes.get(address="0x61994").note


def test_load_code_notes_unescapes_the_markdown_table():
    notes = dict(load_code_notes())

    assert len(notes) == CODE_NOTE_COUNT
    assert notes["0x54b84"] == "Frames"
    assert notes["0x61994"].startswith("Overworld Status:\n00 - In a Stage")
    assert "+0x105 | Papu Papu" in notes["0x60ddc"]
    assert "is_first_zone" in notes["0x61998"]
    assert "2D - Stage Clear screen" in notes["0x6188d"]


@pytest.mark.parametrize(
    ("original", "corrupted_by", "message"),
    [
        ("## All code notes", "## Renamed heading", "has no '## All code notes' table"),
        (
            "| `0x54b84` | 8-bit | Frames |",
            "| `0x54b84` | Frames |",
            f"parsed {CODE_NOTE_COUNT - 1} of {CODE_NOTE_COUNT} code-note rows",
        ),
    ],
)
def test_load_code_notes_refuses_a_malformed_memory_map(
    monkeypatch, tmp_path, original, corrupted_by, message
):
    document = seed_code_notes.CODE_NOTES_PATH.read_text(encoding="utf-8")
    assert original in document

    corrupted = tmp_path / "crash-bandicoot-1.md"
    corrupted.write_text(document.replace(original, corrupted_by), encoding="utf-8")
    monkeypatch.setattr(seed_code_notes, "CODE_NOTES_PATH", corrupted)

    with pytest.raises(ValueError, match=re.escape(message)):
        load_code_notes()


def test_load_code_notes_refuses_an_empty_table(monkeypatch, tmp_path):
    empty = tmp_path / "crash-bandicoot-1.md"
    empty.write_text(
        "## All code notes\n\n| Address | Type | Note |\n| --- | --- | --- |\n", encoding="utf-8"
    )
    monkeypatch.setattr(seed_code_notes, "CODE_NOTES_PATH", empty)

    with pytest.raises(ValueError, match="has no code-note rows"):
        load_code_notes()


@pytest.mark.django_db
def test_seed_crash1_code_notes_command_is_idempotent():
    call_command("seed_crash1_code_notes", verbosity=0)
    call_command("seed_crash1_code_notes", verbosity=0)
    assert CodeNote.objects.filter(game__title="Crash Bandicoot").count() == CODE_NOTE_COUNT


def crash1_game_rows():
    return (
        list(Console.objects.values_list("pk", "ra_id", "name", "short_name")),
        list(Game.objects.values_list("pk", "title", "console_id")),
        list(GameHash.objects.values_list("pk", "md5", "label", "game_id")),
        list(User.objects.values_list("pk", "username", "is_active")),
    )


@pytest.mark.django_db
@pytest.mark.parametrize("command", SEED_COMMANDS)
def test_seed_registers_the_crash1_usa_disc_hash(command):
    call_command(command, verbosity=0)

    disc_hash = GameHash.objects.get(md5=USA_DISC_MD5)
    assert disc_hash.label == USA_DISC_LABEL
    assert disc_hash.game == Game.objects.get(title=GAME_TITLE, console__ra_id=PS1_RA_ID)


@pytest.mark.django_db
def test_seeding_the_crash1_game_twice_is_a_no_op():
    for command in SEED_COMMANDS:
        call_command(command, verbosity=0)
    seeded = crash1_game_rows()

    for command in SEED_COMMANDS:
        call_command(command, verbosity=0)

    assert crash1_game_rows() == seeded
    consoles, games, hashes, users = seeded
    assert (len(consoles), len(games), len(hashes), len(users)) == (1, 1, 1, 1)


@pytest.mark.django_db
@pytest.mark.parametrize("command", SEED_COMMANDS)
def test_seed_refuses_a_usa_disc_hash_that_belongs_to_another_game(command):
    console = Console.objects.create(ra_id=PS1_RA_ID, name="PlayStation", short_name="PS1")
    other_game = Game.objects.create(title="Crash Bandicoot (USA)", console=console)
    GameHash.objects.create(game=other_game, md5=USA_DISC_MD5, label=USA_DISC_LABEL)

    with pytest.raises(CommandError, match=f"{USA_DISC_MD5} belongs to game {other_game.pk}"):
        call_command(command, verbosity=0)

    assert GameHash.objects.get(md5=USA_DISC_MD5).game == other_game
    assert not Game.objects.filter(title=GAME_TITLE).exists()
    assert not Achievement.objects.exists()
    assert not CodeNote.objects.exists()
    assert not Leaderboard.objects.exists()


@pytest.mark.django_db
def test_gameid_does_not_know_the_usa_disc_before_seeding(client):
    data = client.post("/dorequest.php", {"r": "gameid", "m": USA_DISC_MD5}).json()

    assert data["Success"] is True
    assert data["GameID"] == 0


@pytest.mark.django_db
@pytest.mark.parametrize("command", SEED_COMMANDS)
def test_gameid_resolves_the_usa_disc_after_seeding(client, command):
    call_command(command, verbosity=0)

    data = client.post("/dorequest.php", {"r": "gameid", "m": USA_DISC_MD5}).json()

    assert data["Success"] is True
    assert data["GameID"] == Game.objects.get(title=GAME_TITLE).pk


@pytest.fixture
def seeded_game(db):
    call_command("seed_crash1_level_achievements", verbosity=0)
    return Game.objects.get(title=GAME_TITLE)


@pytest.fixture
def player_token(db):
    user = User.objects.create_user(
        username="unlocker", password="pw-test-123", email="unlocker@test.local"
    )
    token = "t" * 64
    user.api_token = token
    user.api_token_expires_at = timezone.now() + timedelta(days=14)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    return user, token


@pytest.mark.django_db
def test_seed_level_achievements_creates_community_set(seeded_game):
    achievements = seeded_game.achievements.all()
    assert achievements.count() == LEVEL_COUNT
    for achievement in achievements:
        assert achievement.points == ACHIEVEMENT_POINTS
        assert achievement.status == Achievement.STATUS_COMMUNITY
        assert achievement.type == Achievement.TYPE_PROGRESSION
        assert achievement.author.username == IMPORT_AUTHOR


@pytest.mark.django_db
def test_seed_level_achievements_mem_addr_is_well_formed(seeded_game):
    expected = dict(LEVEL_ACHIEVEMENTS)
    for achievement in seeded_game.achievements.all():
        match = MEM_ADDR_PATTERN.match(achievement.mem_addr)
        assert match, achievement.mem_addr
        assert int(match.group("level_id"), HEX) == expected[achievement.title]
        assert achievement.description == build_description(achievement.title)
    assert len(set(expected.values())) == LEVEL_COUNT


def test_seed_level_achievements_mem_addr_parses_in_rcheevos():
    result = run_mem_addr_checker(*(build_mem_addr(level_id) for _, level_id in LEVEL_ACHIEVEMENTS))
    assert result.returncode == 0, result.stdout + result.stderr


def test_mem_addr_checker_rejects_a_malformed_condition():
    result = run_mem_addr_checker("0xH61998=@@@")
    assert result.returncode == 1, result.stdout + result.stderr


@pytest.mark.django_db
def test_seed_level_achievements_is_idempotent(seeded_game):
    fields = ("pk", "mem_addr", "description", "updated_at")
    seeded = list(seeded_game.achievements.values_list(*fields))

    call_command("seed_crash1_level_achievements", verbosity=0)

    assert list(seeded_game.achievements.values_list(*fields)) == seeded


@pytest.mark.django_db
def test_seed_level_achievements_updates_an_existing_condition_by_title(player_token):
    user, _ = player_token
    call_command("seed_crash1_level_achievements", verbosity=0)
    stale = Achievement.objects.get(title="Jungle Rollers")
    stale.mem_addr = "0xH61998=1_d0xH61998=0"
    stale.description = "Complete Jungle Rollers."
    stale.type = Achievement.TYPE_MISSABLE
    stale.points = EDITED_POINTS
    stale.status = Achievement.STATUS_VERIFIED
    stale.save()
    UserUnlock.objects.create(user=user, achievement=stale, hardcore=False)

    call_command("seed_crash1_level_achievements", verbosity=0)

    updated = Achievement.objects.get(pk=stale.pk)
    assert updated.mem_addr == build_mem_addr(dict(LEVEL_ACHIEVEMENTS)["Jungle Rollers"])
    assert updated.description == build_description("Jungle Rollers")
    assert updated.type == Achievement.TYPE_PROGRESSION
    assert (updated.points, updated.status) == (EDITED_POINTS, Achievement.STATUS_VERIFIED)
    assert UserUnlock.objects.filter(achievement=updated).count() == 1
    assert Achievement.objects.filter(game__title=GAME_TITLE).count() == LEVEL_COUNT


@pytest.mark.django_db
def test_seed_level_achievements_refuses_two_rows_with_one_title():
    call_command("seed_crash1_level_achievements", verbosity=0)
    original = Achievement.objects.get(title="Boulders")
    duplicate = Achievement.objects.create(
        game=original.game,
        author=original.author,
        title="Boulders",
        description="old",
        points=ACHIEVEMENT_POINTS,
        mem_addr="0xH61998=1",
        status=Achievement.STATUS_COMMUNITY,
    )

    with pytest.raises(CommandError, match="2 achievements .* are titled 'Boulders'"):
        call_command("seed_crash1_level_achievements", verbosity=0)

    duplicate.refresh_from_db()
    assert duplicate.mem_addr == "0xH61998=1"


@pytest.mark.django_db
def test_patch_exposes_seeded_level_achievements(client, seeded_game, player_token):
    user, token = player_token
    response = client.post(
        "/dorequest.php", {"r": "patch", "u": user.username, "t": token, "g": seeded_game.pk}
    )
    data = response.json()

    assert data["Success"] is True
    achievements = data["PatchData"]["Achievements"]
    assert len(achievements) == LEVEL_COUNT
    for achievement in achievements:
        assert achievement["Flags"] == ACHIEVEMENT_FLAGS_CORE
        assert achievement["Points"] == ACHIEVEMENT_POINTS
        assert achievement["Type"] == Achievement.TYPE_PROGRESSION
        assert MEM_ADDR_PATTERN.match(achievement["MemAddr"]), achievement["MemAddr"]


def _award_params(user, token, achievement, hardcore):
    """An awardachievement by `user`, signed with `v` as rcheevos signs it."""
    return {
        "r": "awardachievement",
        "u": user.username,
        "t": token,
        "a": achievement.pk,
        "h": hardcore,
        "v": award_validation_hash(achievement.pk, user.username, hardcore == "1", 0),
    }


@pytest.mark.django_db
def test_awardachievement_unlocks_seeded_achievement(client, seeded_game, player_token):
    user, token = player_token
    achievement = seeded_game.achievements.get(title="N. Sanity Beach")

    response = client.post(
        "/dorequest.php",
        _award_params(user, token, achievement, "0"),
    )
    data = response.json()

    assert data["Success"] is True
    assert data["SoftcoreScore"] == ACHIEVEMENT_POINTS
    assert data["Score"] == 0
    assert data["AchievementsRemaining"] == LEVEL_COUNT - 1
    assert UserUnlock.objects.filter(user=user, achievement=achievement, hardcore=False).exists()

    user.refresh_from_db()
    assert user.softcore_points == ACHIEVEMENT_POINTS


@pytest.mark.django_db
def test_awardachievement_seeded_is_one_shot(client, seeded_game, player_token):
    user, token = player_token
    achievement = seeded_game.achievements.get(title="Jungle Rollers")
    payload = _award_params(user, token, achievement, "0")

    client.post("/dorequest.php", payload)
    client.post("/dorequest.php", payload)

    assert UserUnlock.objects.filter(user=user, achievement=achievement).count() == 1
    user.refresh_from_db()
    assert user.softcore_points == ACHIEVEMENT_POINTS


@pytest.mark.django_db
def test_awardachievement_seeded_hardcore_creates_both_unlocks(client, seeded_game, player_token):
    user, token = player_token
    achievement = seeded_game.achievements.get(title="The Great Gate")

    client.post(
        "/dorequest.php",
        _award_params(user, token, achievement, "1"),
    )

    assert UserUnlock.objects.filter(user=user, achievement=achievement, hardcore=False).exists()
    assert UserUnlock.objects.filter(user=user, achievement=achievement, hardcore=True).exists()
    user.refresh_from_db()
    assert user.softcore_points == ACHIEVEMENT_POINTS
    assert user.hardcore_points == ACHIEVEMENT_POINTS


ACHIEVEMENT_CHANGELIST_URL = "/admin/achievements/achievement/"
ALL_STATUSES = [status for status, _ in Achievement.STATUS_CHOICES]
STATUS_ACTIONS = ("publish_as_community", "mark_verified", "move_to_draft")


def _create_with_status(game, user, status):
    return Achievement.objects.create(
        game=game,
        author=user,
        title=f"{status} achievement",
        description="d",
        mem_addr="0xH0001=1",
        status=status,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("action", "target_status", "expected_message"),
    [
        (
            "publish_as_community",
            Achievement.STATUS_COMMUNITY,
            "2 achievements moved to Community.",
        ),
        ("mark_verified", Achievement.STATUS_VERIFIED, "2 achievements moved to Verified."),
        ("move_to_draft", Achievement.STATUS_DRAFT, "2 achievements moved to Draft."),
    ],
)
def test_admin_status_action_changes_only_the_selected_achievements(
    admin_client, game, user, action, target_status, expected_message
):
    selected = [_create_with_status(game, user, status) for status in ALL_STATUSES]
    unselected_status = next(status for status in ALL_STATUSES if status != target_status)
    unselected = _create_with_status(game, user, unselected_status)
    previous = {a.pk: (a.status, a.updated_at) for a in selected}

    response = admin_client.post(
        ACHIEVEMENT_CHANGELIST_URL,
        {"action": action, "_selected_action": [a.pk for a in selected]},
        HTTP_ACCEPT_LANGUAGE="en",
        follow=True,
    )

    assert response.status_code == 200
    assert [str(m) for m in response.context["messages"]] == [expected_message]
    for achievement in selected:
        previous_status, previous_updated_at = previous[achievement.pk]
        achievement.refresh_from_db()
        assert achievement.status == target_status
        if previous_status == target_status:
            assert achievement.updated_at == previous_updated_at
        else:
            assert achievement.updated_at > previous_updated_at
    unselected.refresh_from_db()
    assert unselected.status == unselected_status


@pytest.mark.django_db
def test_admin_status_action_message_is_in_brazilian_portuguese(admin_client, achievement):
    response = admin_client.post(
        ACHIEVEMENT_CHANGELIST_URL,
        {"action": "mark_verified", "_selected_action": [achievement.pk]},
        follow=True,
    )

    assert [str(m) for m in response.context["messages"]] == ["1 conquista movida para Verificado."]


@pytest.mark.django_db
def test_admin_changelist_offers_status_actions_and_coloured_status(admin_client, achievement):
    response = admin_client.get(ACHIEVEMENT_CHANGELIST_URL, HTTP_ACCEPT_LANGUAGE="en")
    body = response.content.decode()

    assert response.status_code == 200
    for action in STATUS_ACTIONS:
        assert f'value="{action}"' in body
    assert 'font-weight: bold;">Draft</span>' in body
    assert "column-flags" not in body


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("filtered_type", "expected_title"),
    [(Achievement.TYPE_MISSABLE, "Missable one"), (Achievement.TYPE_NONE, "Standard one")],
)
def test_admin_changelist_shows_and_filters_by_type(
    admin_client, game, user, filtered_type, expected_title
):
    for title, achievement_type in (
        ("Missable one", Achievement.TYPE_MISSABLE),
        ("Standard one", Achievement.TYPE_NONE),
    ):
        Achievement.objects.create(
            game=game,
            author=user,
            title=title,
            description="d",
            mem_addr="0xH0001=1",
            type=achievement_type,
        )

    response = admin_client.get(
        ACHIEVEMENT_CHANGELIST_URL, {"type__exact": filtered_type}, HTTP_ACCEPT_LANGUAGE="en"
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert "column-type" in body
    assert "?type__exact=missable" in body
    assert [a.title for a in response.context["cl"].result_list] == [expected_title]


@pytest.fixture
def view_only_staff_client(client):
    staff = User.objects.create_user(username="viewer", password="pw-test-123", is_staff=True)
    staff.user_permissions.add(Permission.objects.get(codename="view_achievement"))
    client.force_login(staff)
    return client


@pytest.mark.django_db
def test_admin_status_actions_require_change_permission(view_only_staff_client, achievement):
    changelist = view_only_staff_client.get(ACHIEVEMENT_CHANGELIST_URL, HTTP_ACCEPT_LANGUAGE="en")
    body = changelist.content.decode()

    assert changelist.status_code == 200
    for action in STATUS_ACTIONS:
        assert f'value="{action}"' not in body

    view_only_staff_client.post(
        ACHIEVEMENT_CHANGELIST_URL,
        {"action": "publish_as_community", "_selected_action": [achievement.pk]},
    )

    achievement.refresh_from_db()
    assert achievement.status == Achievement.STATUS_DRAFT


COMMUNITY_POINTS = 10
VERIFIED_POINTS = 25


def _run_status_action(admin_client, action, achievement):
    return admin_client.post(
        ACHIEVEMENT_CHANGELIST_URL, {"action": action, "_selected_action": [achievement.pk]}
    )


def _points_of(player):
    player.refresh_from_db()
    return player.softcore_points, player.hardcore_points


@pytest.fixture
def unlocked_community_and_verified(client, game, user, player_token):
    player, token = player_token
    community = Achievement.objects.create(
        game=game,
        author=user,
        title="Community",
        description="c",
        points=COMMUNITY_POINTS,
        mem_addr="0xH0001=1",
        status=Achievement.STATUS_COMMUNITY,
    )
    verified = Achievement.objects.create(
        game=game,
        author=user,
        title="Verified",
        description="v",
        points=VERIFIED_POINTS,
        mem_addr="0xH0002=1",
        status=Achievement.STATUS_VERIFIED,
    )
    for achievement, hardcore in ((community, "1"), (verified, "0")):
        client.post("/dorequest.php", _award_params(player, token, achievement, hardcore))
    assert _points_of(player) == (COMMUNITY_POINTS + VERIFIED_POINTS, COMMUNITY_POINTS)
    return player, community


@pytest.mark.django_db
def test_admin_move_to_draft_drops_the_points_and_republishing_restores_them(
    admin_client, unlocked_community_and_verified
):
    player, community = unlocked_community_and_verified

    _run_status_action(admin_client, "move_to_draft", community)

    assert _points_of(player) == (VERIFIED_POINTS, 0)
    kept_modes = UserUnlock.objects.filter(user=player, achievement=community)
    assert set(kept_modes.values_list("hardcore", flat=True)) == {False, True}

    _run_status_action(admin_client, "publish_as_community", community)

    assert _points_of(player) == (COMMUNITY_POINTS + VERIFIED_POINTS, COMMUNITY_POINTS)


@pytest.mark.django_db
def test_admin_change_form_status_change_recalculates_the_points(
    admin_client, unlocked_community_and_verified
):
    player, community = unlocked_community_and_verified

    response = admin_client.post(
        f"{ACHIEVEMENT_CHANGELIST_URL}{community.pk}/change/",
        {
            "game": community.game_id,
            "author": community.author_id,
            "title": community.title,
            "description": community.description,
            "points": community.points,
            "mem_addr": community.mem_addr,
            "status": Achievement.STATUS_DRAFT,
            "badge_name": community.badge_name,
        },
    )

    assert response.status_code == 302
    assert _points_of(player) == (VERIFIED_POINTS, 0)


RAISED_COMMUNITY_POINTS = 50


@pytest.mark.django_db
def test_admin_change_form_points_change_recalculates_the_points(
    admin_client, unlocked_community_and_verified
):
    player, community = unlocked_community_and_verified

    response = admin_client.post(
        f"{ACHIEVEMENT_CHANGELIST_URL}{community.pk}/change/",
        {
            "game": community.game_id,
            "author": community.author_id,
            "title": community.title,
            "description": community.description,
            "points": RAISED_COMMUNITY_POINTS,
            "mem_addr": community.mem_addr,
            "status": community.status,
            "badge_name": community.badge_name,
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    assert _points_of(player) == (
        RAISED_COMMUNITY_POINTS + VERIFIED_POINTS,
        RAISED_COMMUNITY_POINTS,
    )


USER_UNLOCK_ADD_URL = "/admin/achievements/userunlock/add/"


@pytest.mark.django_db
def test_admin_added_unlock_records_its_user_as_a_player(admin_client, achievement, user):
    response = admin_client.post(
        USER_UNLOCK_ADD_URL, {"user": user.pk, "achievement": achievement.pk, "hardcore": "on"}
    )

    assert response.status_code == HTTPStatus.FOUND
    unlock = UserUnlock.objects.get(user=user, achievement=achievement)
    player_game = PlayerGame.objects.get(user=user, game=achievement.game)
    assert player_game.first_played_at == unlock.unlocked_at
    assert player_game.last_played_at == unlock.unlocked_at


@pytest.mark.django_db
def test_admin_added_unlock_keeps_an_existing_player_record(admin_client, achievement, user):
    existing = PlayerGame.objects.create(user=user, game=achievement.game, playtime_seconds=1)

    admin_client.post(USER_UNLOCK_ADD_URL, {"user": user.pk, "achievement": achievement.pk})

    assert list(PlayerGame.objects.all()) == [existing]
    assert PlayerGame.objects.get().playtime_seconds == existing.playtime_seconds


@pytest.mark.django_db
def test_admin_moving_an_achievement_records_its_unlockers_as_players_of_the_new_game(
    admin_client, achievement, user
):
    UserUnlock.objects.create(user=user, achievement=achievement)
    other_game = Game.objects.create(title="Crash Bandicoot 2", console=achievement.game.console)

    response = admin_client.post(
        f"{ACHIEVEMENT_CHANGELIST_URL}{achievement.pk}/change/",
        {
            "game": other_game.pk,
            "author": achievement.author_id,
            "title": achievement.title,
            "description": achievement.description,
            "points": achievement.points,
            "mem_addr": achievement.mem_addr,
            "status": achievement.status,
            "badge_name": achievement.badge_name,
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    assert PlayerGame.objects.filter(user=user, game=other_game).exists()


def test_rich_presence_parses_in_rcheevos():
    script = build_rich_presence()

    result = run_mem_addr_checker(script)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "VALID    rich presence" in result.stdout
    assert len(script.encode()) <= MAX_RICH_PRESENCE_SCRIPT_BYTES


def test_mem_addr_checker_accepts_a_rich_presence_script():
    result = run_mem_addr_checker(
        "Lookup:Stage\n9=N. Sanity Beach\n\nDisplay:\nIn @Stage(0xH6188d)\n"
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_mem_addr_checker_rejects_a_rich_presence_with_an_unknown_macro():
    result = run_mem_addr_checker("Display:\nIn @Stage(0xH6188d)\n")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "unknown macro Stage(0xH6188d)" in result.stdout


def test_mem_addr_checker_rejects_a_rich_presence_without_a_display():
    result = run_mem_addr_checker("Lookup:Stage\n9=N. Sanity Beach\n")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "INVALID  rich presence" in result.stdout


@pytest.mark.django_db
def test_seed_rich_presence_stores_the_script():
    call_command("seed_crash1_rich_presence", verbosity=0)

    assert Game.objects.get(title=GAME_TITLE).rich_presence_patch == build_rich_presence()


@pytest.mark.django_db
def test_seed_rich_presence_is_idempotent():
    call_command("seed_crash1_rich_presence", verbosity=0)
    output = StringIO()

    call_command("seed_crash1_rich_presence", stdout=output)

    assert "already current" in output.getvalue()
    assert Game.objects.get(title=GAME_TITLE).rich_presence_patch == build_rich_presence()


@pytest.mark.django_db
def test_seed_rich_presence_replaces_a_stale_script():
    call_command("seed_crash1_rich_presence", verbosity=0)
    Game.objects.filter(title=GAME_TITLE).update(rich_presence_patch="Display:\nPlaying\n")

    call_command("seed_crash1_rich_presence", verbosity=0)

    assert Game.objects.get(title=GAME_TITLE).rich_presence_patch == build_rich_presence()


@pytest.mark.django_db
def test_patch_serves_the_seeded_rich_presence(client, player_token):
    user, token = player_token
    call_command("seed_crash1_rich_presence", verbosity=0)
    game = Game.objects.get(title=GAME_TITLE)

    data = client.post(
        "/dorequest.php", {"r": "patch", "u": user.username, "t": token, "g": game.pk}
    ).json()

    assert data["Success"] is True
    assert data["PatchData"]["RichPresencePatch"] == build_rich_presence()


@pytest.fixture
def collectibles_game(db):
    call_command("seed_crash1_collectible_achievements", verbosity=0)
    return Game.objects.get(title=GAME_TITLE)


@pytest.mark.django_db
def test_seed_collectible_achievements_creates_community_set(collectibles_game):
    achievements = collectibles_game.achievements.all()

    assert {a.title: a.points for a in achievements} == COLLECTIBLE_POINTS
    for achievement in achievements:
        assert achievement.status == Achievement.STATUS_COMMUNITY
        assert achievement.type == Achievement.TYPE_NONE
        assert achievement.author.username == IMPORT_AUTHOR
        assert achievement.description


def test_collectible_mem_addrs_parse_in_rcheevos():
    result = run_mem_addr_checker(
        *(mem_addr for _, _, mem_addr, _, _ in collectible_achievements())
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("VALID    ") == COLLECTIBLE_COUNT


@pytest.mark.parametrize(
    ("mem_addr", "event"),
    [
        (build_wumpa_mem_addr(), "I:0xW566b4_0xH161<d0xH161"),
        (build_lives_mem_addr(), "I:0xW566b4_0xH165=99_I:0xW566b4_d0xH165<99"),
        (
            build_aku_mem_addr(),
            "0xW618cc=d0xW618cc_I:0xW618cc_0xH189=3_I:0xW618cc_d0xH189<3",
        ),
    ],
)
def test_in_stage_collectibles_fire_on_an_edge_while_the_player_is_in_control(mem_addr, event):
    assert mem_addr == f"{in_play()}_{event}"


def test_in_play_guard_excludes_demos_menus_stage_clear_and_level_loads():
    guard = in_play().split("_")

    assert guard[:4] == ["0xH618d1=1", "0xH61a30=0", "0xH6188d!=h19", "0xH6188d!=h2d"]
    assert "0xW566b4!=0" in guard
    assert "0xW566b4=d0xW566b4" in guard
    assert "R:0xH6188d!=d0xH6188d" in guard
    assert "0xH6188d=0xH6188d.60." in guard


def test_no_wumpa_mem_addr_compares_the_committed_count_on_the_clear_frame():
    assert build_no_wumpa_mem_addr(NSANITY_BEACH_LEVEL_ID) == (
        "0xH61a30=0_0xH6188d=h09_d0xH618d1=1_0xH618f5=d0xH618f5S0xH618d1=5S0xH618d1=3"
    )


@pytest.mark.django_db
def test_seed_collectible_achievements_is_idempotent(collectibles_game):
    fields = ("pk", "mem_addr", "description", "updated_at")
    seeded = list(collectibles_game.achievements.values_list(*fields))
    output = StringIO()

    call_command("seed_crash1_collectible_achievements", stdout=output)

    assert list(collectibles_game.achievements.values_list(*fields)) == seeded
    assert "0 created, 0 updated" in output.getvalue()


@pytest.mark.django_db
def test_seed_collectible_achievements_updates_an_existing_condition_by_title(player_token):
    user, _ = player_token
    call_command("seed_crash1_collectible_achievements", verbosity=0)
    stale = Achievement.objects.get(title=AKU_TITLE)
    stale.mem_addr = "0xH000189=3"
    stale.description = "old"
    stale.points = EDITED_COLLECTIBLE_POINTS
    stale.status = Achievement.STATUS_VERIFIED
    stale.save()
    UserUnlock.objects.create(user=user, achievement=stale, hardcore=False)

    call_command("seed_crash1_collectible_achievements", verbosity=0)

    updated = Achievement.objects.get(pk=stale.pk)
    seeded = {
        title: (description, mem_addr)
        for title, description, mem_addr, _, _ in collectible_achievements()
    }
    assert (updated.description, updated.mem_addr) == seeded[AKU_TITLE]
    assert (updated.points, updated.status) == (
        EDITED_COLLECTIBLE_POINTS,
        Achievement.STATUS_VERIFIED,
    )
    assert UserUnlock.objects.filter(achievement=updated).count() == 1


@pytest.mark.django_db
def test_seed_collectible_achievements_refuses_two_rows_with_one_title(collectibles_game):
    original = collectibles_game.achievements.get(title=WUMPA_TITLE)
    Achievement.objects.create(
        game=collectibles_game,
        author=original.author,
        title=WUMPA_TITLE,
        description="old",
        points=WUMPA_POINTS,
        mem_addr="0xH000161=0",
        status=Achievement.STATUS_COMMUNITY,
    )

    with pytest.raises(CommandError, match=f"2 achievements .* are titled '{WUMPA_TITLE}'"):
        call_command("seed_crash1_collectible_achievements", verbosity=0)


@pytest.mark.django_db
def test_achievement_seeds_share_the_game_without_clashing():
    call_command("seed_crash1_level_achievements", verbosity=0)
    call_command("seed_crash1_collectible_achievements", verbosity=0)
    call_command("seed_crash1_advanced_achievements", verbosity=0)

    titles = list(
        Achievement.objects.filter(game__title=GAME_TITLE).values_list("title", flat=True)
    )
    assert len(titles) == LEVEL_COUNT + COLLECTIBLE_COUNT + ADVANCED_COUNT
    assert len(set(titles)) == len(titles)


@pytest.mark.django_db
def test_patch_exposes_seeded_collectible_achievements(client, collectibles_game, player_token):
    user, token = player_token

    data = client.post(
        "/dorequest.php", {"r": "patch", "u": user.username, "t": token, "g": collectibles_game.pk}
    ).json()

    assert data["Success"] is True
    served = {a["Title"]: (a["MemAddr"], a["Points"]) for a in data["PatchData"]["Achievements"]}
    assert served == {
        title: (mem_addr, points) for title, _, mem_addr, points, _ in collectible_achievements()
    }


@pytest.mark.django_db
def test_awardachievement_scores_a_seeded_collectible(client, collectibles_game, player_token):
    user, token = player_token
    achievement = collectibles_game.achievements.get(title=LIVES_TITLE)

    data = client.post(
        "/dorequest.php",
        _award_params(user, token, achievement, "1"),
    ).json()

    assert data["Success"] is True
    assert data["AchievementsRemaining"] == COLLECTIBLE_COUNT - 1
    user.refresh_from_db()
    assert (user.softcore_points, user.hardcore_points) == (CHALLENGE_POINTS, CHALLENGE_POINTS)


@pytest.fixture
def advanced_game(db):
    call_command("seed_crash1_advanced_achievements", verbosity=0)
    return Game.objects.get(title=GAME_TITLE)


@pytest.mark.django_db
def test_seed_advanced_achievements_creates_community_set(advanced_game):
    achievements = advanced_game.achievements.all()

    assert {a.title: a.points for a in achievements} == ADVANCED_POINTS
    assert {a.title: a.type for a in achievements} == {
        **{title: Achievement.TYPE_NONE for title, *_ in GEM_ACHIEVEMENTS},
        BOSS_TITLE: Achievement.TYPE_PROGRESSION,
    }
    for achievement in achievements:
        assert achievement.status == Achievement.STATUS_COMMUNITY
        assert achievement.author.username == IMPORT_AUTHOR
        assert achievement.description


def test_advanced_mem_addrs_parse_in_rcheevos():
    result = run_mem_addr_checker(*(mem_addr for _, _, mem_addr, _, _ in advanced_achievements()))

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("VALID    ") == ADVANCED_COUNT


@pytest.mark.parametrize(
    ("map_index", "bit"),
    [(0x00, "0xN61988"), (0x04, "0xR61988"), (HOG_WILD_MAP_INDEX, "0xM61989")],
)
def test_gem_bit_of_map_stage_n_is_bit_n_plus_one_from_the_gem_bitfield(map_index, bit):
    assert gem_bit(map_index) == bit


def test_gem_mem_addr_fires_when_the_stage_clear_screen_sets_the_gem_bit():
    assert build_gem_mem_addr(0x00) == "0xH6188d=h2d_d0xH6188d=h2d_0xN61988=1_d0xN61988=0"


def test_boss_mem_addr_fires_on_the_last_hit_of_the_same_boss_object():
    assert build_boss_mem_addr(PAPU_PAPU_LEVEL_ID) == (
        f"{in_play()}_0xH6188d=h0a_0xW60ddc!=0_0xW60ddc=d0xW60ddc_"
        "I:0xW60ddc_0xH105=0_I:0xW60ddc_d0xH105=1"
    )


@pytest.mark.django_db
def test_seed_advanced_achievements_is_idempotent(advanced_game):
    fields = ("pk", "mem_addr", "description", "updated_at")
    seeded = list(advanced_game.achievements.values_list(*fields))
    output = StringIO()

    call_command("seed_crash1_advanced_achievements", stdout=output)

    assert list(advanced_game.achievements.values_list(*fields)) == seeded
    assert "0 created, 0 updated" in output.getvalue()


@pytest.mark.django_db
def test_seed_advanced_achievements_updates_an_existing_condition_by_title(player_token):
    user, _ = player_token
    call_command("seed_crash1_advanced_achievements", verbosity=0)
    stale = Achievement.objects.get(title=BOSS_TITLE)
    stale.mem_addr = "0xH000105=0"
    stale.description = "old"
    stale.points = EDITED_ADVANCED_POINTS
    stale.status = Achievement.STATUS_VERIFIED
    stale.save()
    UserUnlock.objects.create(user=user, achievement=stale, hardcore=False)

    call_command("seed_crash1_advanced_achievements", verbosity=0)

    updated = Achievement.objects.get(pk=stale.pk)
    seeded = {
        title: (description, mem_addr)
        for title, description, mem_addr, _, _ in advanced_achievements()
    }
    assert (updated.description, updated.mem_addr) == seeded[BOSS_TITLE]
    assert (updated.points, updated.status) == (EDITED_ADVANCED_POINTS, Achievement.STATUS_VERIFIED)
    assert UserUnlock.objects.filter(achievement=updated).count() == 1


@pytest.mark.django_db
def test_seed_advanced_achievements_refuses_two_rows_with_one_title(advanced_game):
    original = advanced_game.achievements.get(title=BOSS_TITLE)
    Achievement.objects.create(
        game=advanced_game,
        author=original.author,
        title=BOSS_TITLE,
        description="old",
        points=BOSS_POINTS,
        mem_addr="0xH000105=0",
        status=Achievement.STATUS_COMMUNITY,
    )

    with pytest.raises(CommandError, match=f"2 achievements .* are titled '{BOSS_TITLE}'"):
        call_command("seed_crash1_advanced_achievements", verbosity=0)


@pytest.mark.django_db
def test_patch_exposes_seeded_advanced_achievements(client, advanced_game, player_token):
    user, token = player_token

    data = client.post(
        "/dorequest.php", {"r": "patch", "u": user.username, "t": token, "g": advanced_game.pk}
    ).json()

    assert data["Success"] is True
    served = {
        a["Title"]: (a["MemAddr"], a["Points"], a["Type"])
        for a in data["PatchData"]["Achievements"]
    }
    assert served == {
        title: (mem_addr, points, achievement_type)
        for title, _, mem_addr, points, achievement_type in advanced_achievements()
    }


LEADERBOARD_COUNT = len(leaderboards())
EDITED_SCORE = 1234
# The four sections rcheevos' `rc_parse_lboard` reads, in order.
LEADERBOARD_SECTIONS = ("STA", "CAN", "SUB", "VAL")


@pytest.fixture
def leaderboard_game(db):
    call_command("seed_crash1_leaderboards", verbosity=0)
    return Game.objects.get(title=GAME_TITLE)


def leaderboard_sections(mem_addr):
    """`STA:...::CAN:...` -> {"STA": ..., "CAN": ...}, in order."""
    return dict(part.split(":", 1) for part in mem_addr.split("::"))


@pytest.mark.django_db
def test_seed_leaderboards_creates_frame_timers_where_lower_is_better(leaderboard_game):
    seeded = {
        title: (description, mem_addr) for title, description, mem_addr, _, _ in leaderboards()
    }

    rows = list(leaderboard_game.leaderboards.all())

    assert {row.title: (row.description, row.mem_addr) for row in rows} == seeded
    assert len(rows) == LEADERBOARD_COUNT
    for row in rows:
        assert (row.format, row.lower_is_better) == (LEADERBOARD_FORMAT, True)
        assert row.author.username == IMPORT_AUTHOR


def test_leaderboards_submit_on_their_stage_clear_achievement_condition():
    for _title, _description, mem_addr, level_id, opening in leaderboards():
        sections = leaderboard_sections(mem_addr)
        assert list(sections) == list(LEADERBOARD_SECTIONS)
        assert sections["SUB"] == build_mem_addr(level_id)
        assert mem_addr == build_leaderboard_mem(level_id, opening)


def test_leaderboards_cancel_on_a_quit_or_a_game_over_not_on_the_title_level():
    """A Tawna bonus round's save screen is on the title/map level and returns to the stage."""
    for _title, _description, mem_addr, _level_id, _opening in leaderboards():
        sections = leaderboard_sections(mem_addr)
        assert sections["CAN"] == "S0xH618d1=4S0xH618d1=2"
        assert "_P:0xH6188d=h19_" in sections["VAL"]


def test_leaderboard_start_follows_how_the_stage_opens():
    jungle_rollers_level_id = dict(LEVEL_ACHIEVEMENTS)["Jungle Rollers"]

    assert build_start(NSANITY_BEACH_LEVEL_ID, INTRO).endswith("_0xH618a1=0_d0xH618d1!=1")
    assert build_start(jungle_rollers_level_id, SPIN_IN).endswith(
        "_0xH618a1=0_0xW566b4=d0xW566b4_I:0xW566b4_d0xT121=1_I:0xW566b4_0xT121!=1"
    )
    with pytest.raises(ValueError, match="unknown stage opening"):
        build_start(NSANITY_BEACH_LEVEL_ID, "cutscene")


def test_leaderboards_time_distinct_stages():
    level_ids = [level_id for _, _, _, level_id, _ in leaderboards()]

    assert len(set(level_ids)) == LEADERBOARD_COUNT
    assert set(level_ids) <= set(dict(LEVEL_ACHIEVEMENTS).values())


def test_leaderboards_parse_in_rcheevos():
    result = run_mem_addr_checker(*(mem_addr for _, _, mem_addr, _, _ in leaderboards()))

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("VALID    ") == LEADERBOARD_COUNT


@pytest.mark.django_db
def test_seed_leaderboards_is_idempotent(leaderboard_game):
    fields = ("pk", "title", "description", "mem_addr", "format", "lower_is_better")
    seeded = list(leaderboard_game.leaderboards.values_list(*fields))
    output = StringIO()

    call_command("seed_crash1_leaderboards", stdout=output)

    assert list(leaderboard_game.leaderboards.values_list(*fields)) == seeded
    assert "0 created, 0 updated" in output.getvalue()


@pytest.mark.django_db
def test_seed_leaderboards_updates_an_existing_definition_by_title(leaderboard_game, player_token):
    user, _ = player_token
    title, description, mem_addr, _, _ = leaderboards()[0]
    stale = leaderboard_game.leaderboards.get(title=title)
    stale.description = "old"
    stale.mem_addr = "STA:0xH61998=1::CAN:0=1::SUB:0xH61994=1::VAL:M:1=1"
    stale.format = "SCORE"
    stale.lower_is_better = False
    stale.author = user
    stale.save()
    LeaderboardEntry.objects.create(leaderboard=stale, user=user, score=EDITED_SCORE)

    call_command("seed_crash1_leaderboards", verbosity=0)

    updated = Leaderboard.objects.get(pk=stale.pk)
    assert (updated.description, updated.mem_addr) == (description, mem_addr)
    assert (updated.format, updated.lower_is_better) == (LEADERBOARD_FORMAT, True)
    assert updated.author == user
    assert LeaderboardEntry.objects.get(leaderboard=updated).score == EDITED_SCORE
    assert leaderboard_game.leaderboards.count() == LEADERBOARD_COUNT


@pytest.mark.django_db
def test_seed_leaderboards_refuses_two_rows_with_one_title(leaderboard_game):
    first_title, last_title = leaderboards()[0][0], leaderboards()[-1][0]
    first = leaderboard_game.leaderboards.get(title=first_title)
    first.description = "old"
    first.save()
    Leaderboard.objects.create(
        game=leaderboard_game, title=last_title, mem_addr="STA:0=1::CAN:0=1::SUB:0=1::VAL:M:1=1"
    )

    with pytest.raises(CommandError, match=f"2 leaderboards .* are titled '{last_title}'"):
        call_command("seed_crash1_leaderboards", verbosity=0)

    first.refresh_from_db()
    assert first.description == "old"


@pytest.mark.django_db
def test_patch_serves_the_seeded_leaderboards(client, leaderboard_game, player_token):
    user, token = player_token

    data = client.post(
        "/dorequest.php", {"r": "patch", "u": user.username, "t": token, "g": leaderboard_game.pk}
    ).json()

    assert data["Success"] is True
    served = {
        lb["Title"]: (lb["Mem"], lb["Format"], lb["LowerIsBetter"])
        for lb in data["PatchData"]["Leaderboards"]
    }
    assert served == {
        title: (mem_addr, LEADERBOARD_FORMAT, True) for title, _, mem_addr, _, _ in leaderboards()
    }
