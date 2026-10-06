import re
import subprocess
from datetime import timedelta
from io import StringIO
from pathlib import Path

import pytest
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
from apps.games.models import Console, Game, GameHash

MEM_ADDR_PATTERN = re.compile(r"^0xH6188d=h2d_d0xH6188d=h(?P<level_id>[0-9a-f]{2})$")
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
    assert achievement.flags == 5
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
    stale.points = EDITED_POINTS
    stale.status = Achievement.STATUS_VERIFIED
    stale.save()
    UserUnlock.objects.create(user=user, achievement=stale, hardcore=False)

    call_command("seed_crash1_level_achievements", verbosity=0)

    updated = Achievement.objects.get(pk=stale.pk)
    assert updated.mem_addr == build_mem_addr(dict(LEVEL_ACHIEVEMENTS)["Jungle Rollers"])
    assert updated.description == build_description("Jungle Rollers")
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
    _, token = player_token
    response = client.post("/dorequest.php", {"r": "patch", "t": token, "g": seeded_game.pk})
    data = response.json()

    assert data["Success"] is True
    achievements = data["PatchData"]["Achievements"]
    assert len(achievements) == LEVEL_COUNT
    for achievement in achievements:
        assert achievement["Flags"] == 5
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
    _, token = player_token
    call_command("seed_crash1_rich_presence", verbosity=0)
    game = Game.objects.get(title=GAME_TITLE)

    data = client.post("/dorequest.php", {"r": "patch", "t": token, "g": game.pk}).json()

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
        assert achievement.author.username == IMPORT_AUTHOR
        assert achievement.description


def test_collectible_mem_addrs_parse_in_rcheevos():
    result = run_mem_addr_checker(*(mem_addr for _, _, mem_addr, _ in collectible_achievements()))

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
        "0xH61a30=0_0xH6188d=h09_d0xH618d1=1_0xH618d1=5_0xH618f5=d0xH618f5"
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
        for title, description, mem_addr, _ in (collectible_achievements())
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
    _, token = player_token

    data = client.post(
        "/dorequest.php", {"r": "patch", "t": token, "g": collectibles_game.pk}
    ).json()

    assert data["Success"] is True
    served = {a["Title"]: (a["MemAddr"], a["Points"]) for a in data["PatchData"]["Achievements"]}
    assert served == {
        title: (mem_addr, points) for title, _, mem_addr, points in collectible_achievements()
    }


@pytest.mark.django_db
def test_awardachievement_scores_a_seeded_collectible(client, collectibles_game, player_token):
    user, token = player_token
    achievement = collectibles_game.achievements.get(title=LIVES_TITLE)

    data = client.post(
        "/dorequest.php",
        {"r": "awardachievement", "t": token, "a": achievement.pk, "h": "1"},
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
    for achievement in achievements:
        assert achievement.status == Achievement.STATUS_COMMUNITY
        assert achievement.author.username == IMPORT_AUTHOR
        assert achievement.description


def test_advanced_mem_addrs_parse_in_rcheevos():
    result = run_mem_addr_checker(*(mem_addr for _, _, mem_addr, _ in advanced_achievements()))

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
        for title, description, mem_addr, _ in advanced_achievements()
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
    _, token = player_token

    data = client.post("/dorequest.php", {"r": "patch", "t": token, "g": advanced_game.pk}).json()

    assert data["Success"] is True
    served = {a["Title"]: (a["MemAddr"], a["Points"]) for a in data["PatchData"]["Achievements"]}
    assert served == {
        title: (mem_addr, points) for title, _, mem_addr, points in advanced_achievements()
    }
