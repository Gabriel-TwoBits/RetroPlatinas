import re
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import IntegrityError
from django.utils import timezone

from apps.accounts.models import User
from apps.achievements.management.commands import seed_crash1_code_notes as seed_code_notes
from apps.achievements.management.commands.seed_crash1_code_notes import load_code_notes
from apps.achievements.management.commands.seed_crash1_level_achievements import (
    ACHIEVEMENT_POINTS,
    FRAMES_OF_PLAY_BEFORE_ARMED,
    GAME_TITLE,
    IMPORT_AUTHOR,
    LEVEL_ACHIEVEMENTS,
    build_mem_addr,
)
from apps.achievements.models import Achievement, CodeNote, UserUnlock
from apps.api.handlers import ACHIEVEMENT_FLAGS_CORE
from apps.games.models import Console, Game

MEM_ADDR_PATTERN = re.compile(
    r"^N:0xW618cc!=0_N:0xH61994=0_N:0xH619c5=(?P<armed_stage_id>\d+)_"
    rf"0xH61998=0\.{FRAMES_OF_PLAY_BEFORE_ARMED}\._"
    r"R:0xH61994=1_R:0xW618cc=0_"
    r"0xH61998=1_d0xH61998=0_0xH619c5=(?P<stage_id>\d+)_0xH61994=0$"
)
LEVEL_COUNT = len(LEVEL_ACHIEVEMENTS)
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
    assert notes.count() == 108
    assert "N. Sanity Beach" in notes.get(address="0x619c5").note
    assert "Overworld" in notes.get(address="0x61994").note


def test_load_code_notes_unescapes_the_markdown_table():
    notes = dict(load_code_notes())

    assert len(notes) == 108
    assert notes["0x54b84"] == "Frames"
    assert notes["0x61994"].startswith("Overworld Status:\n00 - In a Stage")
    assert "+0x105 | Papu Papu" in notes["0x60ddc"]


@pytest.mark.parametrize(
    ("original", "corrupted_by", "message"),
    [
        ("## All code notes", "## Renamed heading", "has no '## All code notes' table"),
        (
            "| `0x54b84` | 8-bit | Frames |",
            "| `0x54b84` | Frames |",
            "parsed 107 of 108 code-note rows",
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
    assert CodeNote.objects.filter(game__title="Crash Bandicoot").count() == 108


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
        assert achievement.author.username == IMPORT_AUTHOR


@pytest.mark.django_db
def test_seed_level_achievements_mem_addr_is_well_formed(seeded_game):
    expected_titles = {title for title, _ in LEVEL_ACHIEVEMENTS}
    expected_stage_ids = {stage_id for _, stage_id in LEVEL_ACHIEVEMENTS}
    found_stage_ids = set()
    for achievement in seeded_game.achievements.all():
        assert achievement.title in expected_titles
        match = MEM_ADDR_PATTERN.match(achievement.mem_addr)
        assert match, achievement.mem_addr
        assert match.group("armed_stage_id") == match.group("stage_id"), achievement.mem_addr
        found_stage_ids.add(int(match.group("stage_id")))
    assert found_stage_ids == expected_stage_ids


def test_seed_level_achievements_mem_addr_parses_in_rcheevos():
    result = run_mem_addr_checker(*(build_mem_addr(stage_id) for _, stage_id in LEVEL_ACHIEVEMENTS))
    assert result.returncode == 0, result.stdout + result.stderr


def test_mem_addr_checker_rejects_a_malformed_condition():
    result = run_mem_addr_checker("0xH61998=@@@")
    assert result.returncode == 1, result.stdout + result.stderr


@pytest.mark.django_db
def test_seed_level_achievements_is_idempotent(seeded_game):
    call_command("seed_crash1_level_achievements", verbosity=0)
    assert seeded_game.achievements.count() == LEVEL_COUNT


@pytest.mark.django_db
def test_patch_exposes_seeded_level_achievements(client, seeded_game, player_token):
    _, token = player_token
    response = client.post("/dorequest.php", {"r": "patch", "t": token, "g": seeded_game.pk})
    data = response.json()

    assert data["Success"] is True
    achievements = data["PatchData"]["Achievements"]
    assert len(achievements) == LEVEL_COUNT
    for achievement in achievements:
        assert achievement["Flags"] == ACHIEVEMENT_FLAGS_CORE
        assert achievement["Points"] == ACHIEVEMENT_POINTS
        assert MEM_ADDR_PATTERN.match(achievement["MemAddr"]), achievement["MemAddr"]


@pytest.mark.django_db
def test_awardachievement_unlocks_seeded_achievement(client, seeded_game, player_token):
    user, token = player_token
    achievement = seeded_game.achievements.get(title="N. Sanity Beach")

    response = client.post(
        "/dorequest.php",
        {"r": "awardachievement", "t": token, "a": achievement.pk, "h": "0"},
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
    payload = {"r": "awardachievement", "t": token, "a": achievement.pk, "h": "0"}

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
        {"r": "awardachievement", "t": token, "a": achievement.pk, "h": "1"},
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
