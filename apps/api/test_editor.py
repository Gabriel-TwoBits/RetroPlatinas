"""The editor actions RAIntegration calls. The `RCHEEVOS_*` request bodies were produced by
rcheevos v12.4.0's own request builders (`rc_api_editor.c`, `rc_api_info.c`), checksums included,
so these tests hold the server to what the real client sends."""

import io
from datetime import timedelta
from http import HTTPStatus
from urllib.parse import parse_qsl, urlencode

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.achievements.models import (
    MAX_BADGE_UPLOAD_BYTES,
    PLACEHOLDER_BADGE_NAME,
    Achievement,
    Badge,
    CodeNote,
    UserUnlock,
)
from apps.api.editor import (
    MAX_CODE_NOTES_PER_REQUEST,
    achievement_upload_checksum,
    leaderboard_upload_checksum,
)
from apps.api.handlers import (
    ACHIEVEMENT_FLAGS_UNOFFICIAL,
    ACHIEVEMENTWONDATA_DEFAULT_COUNT,
    API_TOKEN_LIFETIME,
)
from apps.games.models import Console, Game, GameHash, PlayerGame
from apps.images.catalog import avatar_path
from apps.images.rendering import BADGE_SIZE_PX
from apps.leaderboards.models import Leaderboard

User = get_user_model()

FORM = "application/x-www-form-urlencoded"
PLAYER = "player"
PLAYER_TOKEN = "tok"
OTHER = "other"
OTHER_TOKEN = "other-tok"
STAFF = "staff"
STAFF_TOKEN = "staff-tok"
PLAYSTATION_RA_ID = 12
# The ids the rcheevos request bodies below were built with.
GAME_ID = 7
ACHIEVEMENT_ID = 42
LEADERBOARD_ID = 9
BADGE_NUMBER = 12
BADGE_NAME = "00012"
WON_ACHIEVEMENT_ID = 3

RCHEEVOS_NEW_ACHIEVEMENT = (
    "r=uploadachievement&u=player&t=tok&g=7&n=Beach&d=Clear+it&m=0xH0001%3d1_0xH0002%3d2"
    "&z=10&f=5&b=00012&x=progression&h=33e3d18c6f76281f574d1b62488748a0"
)
RCHEEVOS_UPDATE_ACHIEVEMENT = (
    "r=uploadachievement&u=player&t=tok&a=42&g=7&n=Beach&d=Clear+it&m=0xH0001%3d1_0xH0002%3d2"
    "&z=10&f=5&b=00012&x=&h=f70c8bdf569ba17ade0cbed27f017e55"
)
RCHEEVOS_TRIGGER = "0xH0001=1_0xH0002=2"
RCHEEVOS_POINTS = 10
RCHEEVOS_NEW_LEADERBOARD = (
    "r=uploadleaderboard&u=player&t=tok&g=7&n=Fastest&d=&s=0xH0001%3d1&b=0xH0002%3d1"
    "&c=0xH0003%3d1&l=M%3a0xH0004&w=1&f=FRAMES&h=9dc4b4ed5fbf36b007c8cfba83810d45"
)
RCHEEVOS_UPDATE_LEADERBOARD = (
    "r=uploadleaderboard&u=player&t=tok&i=9&g=7&n=Fastest&d=&s=0xH0001%3d1&b=0xH0002%3d1"
    "&c=0xH0003%3d1&l=M%3a0xH0004&w=1&f=FRAMES&h=079e343e19a0f3fe42e1064d071c11aa"
)
RCHEEVOS_LEADERBOARD_MEM = "STA:0xH0001=1::CAN:0xH0003=1::SUB:0xH0002=1::VAL:M:0xH0004"
# Notes "Lives\r\nBit0 - x\y" at 0x1234, none (a delete) at 0x61994 and "a:b" at 0x10.
RCHEEVOS_CODE_NOTES = (
    "r=submitcodenotes&u=player&t=tok&g=7"
    "&n=4660:Lives%5cr%5cnBit0+-+x%5c%5cy%0a399764:%0a16:a%3ab%0a"
)
# An empty note, which rcheevos sends as a delete by leaving `n` out.
RCHEEVOS_DELETE_CODE_NOTE = "r=submitcodenote&u=player&t=tok&g=7&m=4660"
RCHEEVOS_GAME_HASH = (
    "r=submitgametitle&u=staff&t=staff-tok&c=12&m=35386fd0891e594c9b6d8a4a5baa0027&i=Crash&d=USA"
)
RCHEEVOS_GAME_HASH_MD5 = "35386fd0891e594c9b6d8a4a5baa0027"
# Friends only, entries 11 onwards, 10 of them.
RCHEEVOS_ACHIEVEMENT_WON_DATA = "r=achievementwondata&u=player&t=tok&a=3&f=1&o=10&c=10"

ACCESS_DENIED = {"Success": False, "Status": HTTPStatus.FORBIDDEN, "Code": "access_denied"}
INVALID_CHECKSUM = {**ACCESS_DENIED, "Error": "Invalid checksum."}
NOT_THE_AUTHOR = {**ACCESS_DENIED, "Error": "Only the author or staff can change this."}
STAFF_ONLY = {**ACCESS_DENIED, "Error": "Only staff can perform this action."}
MISSING_PARAMETER = {
    "Success": False,
    "Error": "One or more required parameters is missing.",
    "Status": HTTPStatus.UNPROCESSABLE_ENTITY,
    "Code": "missing_parameter",
}
INVALID_CREDENTIALS = {
    "Success": False,
    "Error": "Credentials invalid.",
    "Status": HTTPStatus.UNAUTHORIZED,
    "Code": "invalid_credentials",
}


def _not_found(resource):
    return {
        "Success": False,
        "Error": f"Unknown {resource}.",
        "Status": HTTPStatus.NOT_FOUND,
        "Code": "not_found",
    }


def _invalid(message):
    return {
        "Success": False,
        "Error": message,
        "Status": HTTPStatus.UNPROCESSABLE_ENTITY,
        "Code": "invalid_parameter",
    }


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    cache.clear()


def _user(username, token, is_staff=False):
    user = User.objects.create_user(username=username, password="pw", is_staff=is_staff)
    user.api_token = token
    user.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    user.save(update_fields=["api_token", "api_token_expires_at"])
    return user


@pytest.fixture
def player(db):
    return _user(PLAYER, PLAYER_TOKEN)


@pytest.fixture
def other(db):
    return _user(OTHER, OTHER_TOKEN)


@pytest.fixture
def staff(db):
    return _user(STAFF, STAFF_TOKEN, is_staff=True)


@pytest.fixture
def console(db):
    return Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")


@pytest.fixture
def game(console):
    return Game.objects.create(pk=GAME_ID, title="Crash Bandicoot", console=console)


def _png(size=BADGE_SIZE_PX, image_format="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), "red").save(buffer, format=image_format)
    return buffer.getvalue()


# Noise keeps every part of the file load-bearing, so cutting it loses pixels.
NOISE_SIGMA = 64


def _truncated(image_format):
    """A noisy badge in `image_format` cut in half: its header is intact, its pixels are not."""
    buffer = io.BytesIO()
    noise = Image.effect_noise((BADGE_SIZE_PX, BADGE_SIZE_PX), NOISE_SIGMA).convert("RGB")
    noise.save(buffer, format=image_format)
    content = buffer.getvalue()
    return content[: len(content) // 2]


@pytest.fixture
def badge(db):
    return Badge.objects.create(pk=BADGE_NUMBER, image=SimpleUploadedFile("b.png", _png()))


def _raw(client, body, path="/dorequest.php"):
    return client.post(path, body, content_type=FORM).json()


def _post(client, **params):
    return client.post("/dorequest.php", params).json()


def _with(body, **changes):
    """The urlencoded `body` with `changes` applied to its parameters."""
    params = dict(parse_qsl(body, keep_blank_values=True))
    params.update(changes)
    return urlencode(params)


# --- uploadachievement ---


def _achievement(game, author, status=Achievement.STATUS_COMMUNITY, **fields):
    return Achievement.objects.create(
        game=game,
        author=author,
        title="Old",
        description="old",
        points=5,
        mem_addr="0xH0009=9",
        status=status,
        type=Achievement.TYPE_MISSABLE,
        **fields,
    )


def _signed_achievement(username, token, achievement_id=0, **overrides):
    """An uploadachievement signed as rcheevos signs it, with `overrides` applied."""
    params = {
        "r": "uploadachievement",
        "u": username,
        "t": token,
        "g": GAME_ID,
        "n": "Beach",
        "d": "Clear it",
        "m": RCHEEVOS_TRIGGER,
        "z": RCHEEVOS_POINTS,
        "f": ACHIEVEMENT_FLAGS_UNOFFICIAL,
        "b": PLACEHOLDER_BADGE_NAME,
        "x": "",
        **overrides,
    }
    if achievement_id:
        params["a"] = achievement_id
    params["h"] = achievement_upload_checksum(username, achievement_id, params["m"], params["z"])
    return params


def test_achievement_upload_checksum_matches_rcheevos():
    new = dict(parse_qsl(RCHEEVOS_NEW_ACHIEVEMENT))
    update = dict(parse_qsl(RCHEEVOS_UPDATE_ACHIEVEMENT, keep_blank_values=True))

    assert achievement_upload_checksum(PLAYER, 0, RCHEEVOS_TRIGGER, RCHEEVOS_POINTS) == new["h"]
    assert (
        achievement_upload_checksum(PLAYER, ACHIEVEMENT_ID, RCHEEVOS_TRIGGER, RCHEEVOS_POINTS)
        == update["h"]
    )


@pytest.mark.django_db
def test_uploadachievement_creates_a_draft_by_its_uploader(client, player, game, badge):
    data = _raw(client, RCHEEVOS_NEW_ACHIEVEMENT)

    achievement = Achievement.objects.get()
    assert data == {"Success": True, "AchievementID": achievement.pk}
    assert achievement.status == Achievement.STATUS_DRAFT
    assert achievement.author == player
    assert achievement.game == game
    assert (achievement.title, achievement.description) == ("Beach", "Clear it")
    assert achievement.mem_addr == RCHEEVOS_TRIGGER
    assert achievement.points == RCHEEVOS_POINTS
    assert achievement.badge_name == BADGE_NAME
    assert achievement.type == Achievement.TYPE_PROGRESSION


@pytest.mark.django_db
def test_uploaded_achievement_reaches_only_its_author_as_unofficial(
    client, player, other, game, badge
):
    achievement_id = _raw(client, RCHEEVOS_NEW_ACHIEVEMENT)["AchievementID"]

    def served(user, token):
        data = _post(client, r="achievementsets", u=user.username, t=token, g=GAME_ID)
        return {a["ID"]: a for a in data["Sets"][0]["Achievements"]}

    authors_view = served(player, PLAYER_TOKEN)
    assert authors_view[achievement_id]["Flags"] == ACHIEVEMENT_FLAGS_UNOFFICIAL
    assert authors_view[achievement_id]["BadgeName"] == BADGE_NAME
    assert authors_view[achievement_id]["Type"] == Achievement.TYPE_PROGRESSION
    assert achievement_id not in served(other, OTHER_TOKEN)


@pytest.mark.django_db
def test_uploadachievement_never_publishes_a_new_achievement(client, player, game):
    params = _signed_achievement(PLAYER, PLAYER_TOKEN, f=3)

    assert _post(client, **params)["Success"] is True
    assert Achievement.objects.get().status == Achievement.STATUS_DRAFT


@pytest.mark.django_db
def test_uploadachievement_updates_its_authors_achievement_and_keeps_its_status(
    client, player, game, badge
):
    _achievement(game, player, pk=ACHIEVEMENT_ID)

    data = _raw(client, RCHEEVOS_UPDATE_ACHIEVEMENT)

    assert data == {"Success": True, "AchievementID": ACHIEVEMENT_ID}
    achievement = Achievement.objects.get(pk=ACHIEVEMENT_ID)
    assert achievement.status == Achievement.STATUS_COMMUNITY
    assert achievement.title == "Beach"
    assert achievement.mem_addr == RCHEEVOS_TRIGGER
    assert achievement.points == RCHEEVOS_POINTS
    assert achievement.badge_name == BADGE_NAME
    assert achievement.type == Achievement.TYPE_NONE


@pytest.mark.django_db
def test_uploadachievement_without_x_keeps_the_type(client, player, game):
    achievement = _achievement(game, player)
    params = _signed_achievement(PLAYER, PLAYER_TOKEN, achievement.pk)
    del params["x"]

    assert _post(client, **params)["Success"] is True
    achievement.refresh_from_db()
    assert achievement.type == Achievement.TYPE_MISSABLE


@pytest.mark.django_db
def test_uploadachievement_rejects_a_wrong_checksum(client, player, game, badge):
    data = _raw(client, _with(RCHEEVOS_NEW_ACHIEVEMENT, z="25"))

    assert data == INVALID_CHECKSUM
    assert not Achievement.objects.exists()


@pytest.mark.django_db
def test_uploadachievement_requires_the_checksum(client, player, game):
    params = _signed_achievement(PLAYER, PLAYER_TOKEN)
    del params["h"]

    assert _post(client, **params) == MISSING_PARAMETER


@pytest.mark.django_db
@pytest.mark.parametrize("param", ["n", "d", "m", "z", "f", "b"])
def test_uploadachievement_requires_every_field(client, player, game, param):
    params = _signed_achievement(PLAYER, PLAYER_TOKEN)
    del params[param]

    assert _post(client, **params) == MISSING_PARAMETER
    assert not Achievement.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"z": 7}, "Invalid points value: 7."),
        ({"f": 1}, "Unknown flag: 1."),
        ({"x": "bonus"}, "Unknown type: bonus."),
        ({"b": "00099"}, "Unknown badge: 00099. Upload it first, or use 00000."),
        ({"n": "t" * 256}, "Invalid n: at most 255 characters."),
    ],
)
def test_uploadachievement_rejects_values_the_set_cannot_hold(
    client, player, game, overrides, error
):
    assert _post(client, **_signed_achievement(PLAYER, PLAYER_TOKEN, **overrides)) == _invalid(
        error
    )


@pytest.mark.django_db
def test_uploadachievement_new_needs_a_known_game(client, player, game):
    assert _post(client, **_signed_achievement(PLAYER, PLAYER_TOKEN, g=GAME_ID + 1)) == (
        _not_found("game")
    )
    params = _signed_achievement(PLAYER, PLAYER_TOKEN)
    del params["g"]
    assert _post(client, **params) == MISSING_PARAMETER


@pytest.mark.django_db
def test_uploadachievement_cannot_change_another_authors_achievement(client, player, other, game):
    achievement = _achievement(game, other)

    data = _post(client, **_signed_achievement(PLAYER, PLAYER_TOKEN, achievement.pk))

    assert data == NOT_THE_AUTHOR
    achievement.refresh_from_db()
    assert achievement.title == "Old"


@pytest.mark.django_db
def test_uploadachievement_hides_another_authors_draft(client, player, other, game):
    draft = _achievement(game, other, status=Achievement.STATUS_DRAFT)

    data = _post(client, **_signed_achievement(PLAYER, PLAYER_TOKEN, draft.pk))

    assert data == _not_found("achievement")


@pytest.mark.django_db
@pytest.mark.parametrize("status", [Achievement.STATUS_DRAFT, Achievement.STATUS_VERIFIED])
def test_uploadachievement_lets_staff_change_any_achievement(client, staff, other, game, status):
    achievement = _achievement(game, other, status=status)

    data = _post(client, **_signed_achievement(STAFF, STAFF_TOKEN, achievement.pk))

    assert data == {"Success": True, "AchievementID": achievement.pk}
    achievement.refresh_from_db()
    assert (achievement.title, achievement.status, achievement.author) == ("Beach", status, other)


@pytest.mark.django_db
def test_uploadachievement_cannot_move_an_achievement_to_another_game(
    client, player, game, console
):
    achievement = _achievement(game, player)
    other_game = Game.objects.create(title="Crash 2", console=console)

    data = _post(
        client, **_signed_achievement(PLAYER, PLAYER_TOKEN, achievement.pk, g=other_game.pk)
    )

    assert data == _invalid("Invalid g: the achievement belongs to another game.")


@pytest.mark.django_db
def test_uploadachievement_unknown_achievement(client, player, game):
    data = _post(client, **_signed_achievement(PLAYER, PLAYER_TOKEN, ACHIEVEMENT_ID))

    assert data == _not_found("achievement")


RAISED_POINTS = 25


@pytest.mark.django_db
def test_uploadachievement_new_points_are_recounted_for_its_unlockers(client, player, other, game):
    achievement = _achievement(game, player)
    UserUnlock.objects.create(user=other, achievement=achievement, hardcore=False)
    UserUnlock.objects.create(user=other, achievement=achievement, hardcore=True)

    _post(client, **_signed_achievement(PLAYER, PLAYER_TOKEN, achievement.pk, z=RAISED_POINTS))

    other.refresh_from_db()
    assert (other.softcore_points, other.hardcore_points) == (RAISED_POINTS, RAISED_POINTS)


# --- uploadleaderboard ---


def _leaderboard(game, author, **fields):
    return Leaderboard.objects.create(
        game=game, author=author, title="Old", mem_addr="STA:0=1::CAN:0=1::SUB:0=1::VAL:0", **fields
    )


def _signed_leaderboard(username, token, leaderboard_id=0, **overrides):
    params = {
        "r": "uploadleaderboard",
        "u": username,
        "t": token,
        "g": GAME_ID,
        "n": "Fastest",
        "d": "",
        "s": "0xH0001=1",
        "b": "0xH0002=1",
        "c": "0xH0003=1",
        "l": "M:0xH0004",
        "w": 1,
        "f": "FRAMES",
        **overrides,
    }
    if leaderboard_id:
        params["i"] = leaderboard_id
    params["h"] = leaderboard_upload_checksum(
        username, leaderboard_id, params["s"], params["b"], params["c"], params["l"], params["f"]
    )
    return params


def test_leaderboard_upload_checksum_matches_rcheevos():
    parts = ("0xH0001=1", "0xH0002=1", "0xH0003=1", "M:0xH0004", "FRAMES")
    new = dict(parse_qsl(RCHEEVOS_NEW_LEADERBOARD, keep_blank_values=True))
    update = dict(parse_qsl(RCHEEVOS_UPDATE_LEADERBOARD, keep_blank_values=True))

    assert leaderboard_upload_checksum(PLAYER, 0, *parts) == new["h"]
    assert leaderboard_upload_checksum(PLAYER, LEADERBOARD_ID, *parts) == update["h"]


@pytest.mark.django_db
def test_uploadleaderboard_creates_a_leaderboard_by_its_uploader(client, player, game):
    data = _raw(client, RCHEEVOS_NEW_LEADERBOARD)

    leaderboard = Leaderboard.objects.get()
    assert data == {"Success": True, "LeaderboardID": leaderboard.pk}
    assert leaderboard.author == player
    assert leaderboard.game == game
    assert (leaderboard.title, leaderboard.description) == ("Fastest", "")
    assert leaderboard.mem_addr == RCHEEVOS_LEADERBOARD_MEM
    assert leaderboard.format == Leaderboard.Format.FRAMES
    assert leaderboard.lower_is_better is True
    info = _post(client, r="lbinfo", i=leaderboard.pk)["LeaderboardData"]
    assert info["LBAuthor"] == PLAYER
    assert info["LBMem"] == RCHEEVOS_LEADERBOARD_MEM


@pytest.mark.django_db
def test_uploadleaderboard_updates_its_authors_leaderboard(client, player, game):
    _leaderboard(game, player, pk=LEADERBOARD_ID)

    data = _raw(client, RCHEEVOS_UPDATE_LEADERBOARD)

    assert data == {"Success": True, "LeaderboardID": LEADERBOARD_ID}
    leaderboard = Leaderboard.objects.get(pk=LEADERBOARD_ID)
    assert (leaderboard.title, leaderboard.mem_addr) == ("Fastest", RCHEEVOS_LEADERBOARD_MEM)


@pytest.mark.django_db
def test_uploadleaderboard_stores_a_format_alias_under_its_canonical_name(client, player, game):
    assert _post(client, **_signed_leaderboard(PLAYER, PLAYER_TOKEN, f="TIME"))["Success"] is True
    assert Leaderboard.objects.get().format == Leaderboard.Format.FRAMES


@pytest.mark.django_db
def test_uploadleaderboard_rejects_an_unknown_format(client, player, game):
    data = _post(client, **_signed_leaderboard(PLAYER, PLAYER_TOKEN, f="SECONDS"))

    assert data == _invalid("Unknown format: SECONDS.")


@pytest.mark.django_db
def test_uploadleaderboard_rejects_a_wrong_checksum(client, player, game):
    assert _raw(client, _with(RCHEEVOS_NEW_LEADERBOARD, f="SCORE")) == INVALID_CHECKSUM
    assert not Leaderboard.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("param", ["n", "s", "b", "c", "l", "w", "f", "h"])
def test_uploadleaderboard_requires_every_field(client, player, game, param):
    params = _signed_leaderboard(PLAYER, PLAYER_TOKEN)
    del params[param]

    assert _post(client, **params) == MISSING_PARAMETER


@pytest.mark.django_db
@pytest.mark.parametrize("author_name", [OTHER, None])
def test_uploadleaderboard_cannot_change_a_leaderboard_by_someone_else(
    client, player, other, game, author_name
):
    author = other if author_name else None
    leaderboard = _leaderboard(game, author)

    data = _post(client, **_signed_leaderboard(PLAYER, PLAYER_TOKEN, leaderboard.pk))

    assert data == NOT_THE_AUTHOR
    leaderboard.refresh_from_db()
    assert leaderboard.title == "Old"


@pytest.mark.django_db
def test_uploadleaderboard_lets_staff_change_any_leaderboard(client, staff, game):
    leaderboard = _leaderboard(game, None)

    data = _post(client, **_signed_leaderboard(STAFF, STAFF_TOKEN, leaderboard.pk))

    assert data == {"Success": True, "LeaderboardID": leaderboard.pk}


@pytest.mark.django_db
def test_uploadleaderboard_unknown_leaderboard_or_game(client, player, game):
    assert _post(client, **_signed_leaderboard(PLAYER, PLAYER_TOKEN, LEADERBOARD_ID)) == (
        _not_found("leaderboard")
    )
    assert _post(client, **_signed_leaderboard(PLAYER, PLAYER_TOKEN, g=GAME_ID + 1)) == (
        _not_found("game")
    )


# --- Code notes ---


def _note(game, author, address, text):
    return CodeNote.objects.create(game=game, author=author, address=address, note=text)


@pytest.mark.django_db
def test_codenotes2_serves_notes_without_authentication(client, player, other, game):
    _note(game, other, "0x61994", "Overworld status")
    _note(game, player, "0x001234", "Lives")
    _note(game, player, "0x10", "")

    data = _post(client, r="codenotes2", g=GAME_ID)

    assert data == {
        "Success": True,
        "CodeNotes": [
            {"User": PLAYER, "Address": "0x001234", "Note": "Lives"},
            {"User": OTHER, "Address": "0x061994", "Note": "Overworld status"},
        ],
    }


@pytest.mark.django_db
def test_codenotes2_unknown_or_missing_game(client, game):
    assert _post(client, r="codenotes2", g=GAME_ID + 1) == _not_found("game")
    assert _post(client, r="codenotes2") == MISSING_PARAMETER


@pytest.mark.django_db
def test_submitcodenotes_writes_rcheevos_escaped_notes(client, player, game):
    _note(game, player, "0x61994", "stale")

    data = _raw(client, RCHEEVOS_CODE_NOTES)

    assert data == {"Success": True, "SuccessfulAddresses": [0x1234, 0x61994, 0x10]}
    notes = {note.address: note for note in CodeNote.objects.all()}
    assert set(notes) == {"0x1234", "0x10"}
    assert notes["0x1234"].note == "Lives\r\nBit0 - x\\y"
    assert notes["0x10"].note == "a:b"
    assert notes["0x1234"].author == player
    served = _post(client, r="codenotes2", g=GAME_ID)["CodeNotes"]
    assert [note["Note"] for note in served] == ["a:b", "Lives\r\nBit0 - x\\y"]


@pytest.mark.django_db
def test_submitcodenotes_reports_the_notes_of_others_as_denied(client, player, other, game):
    theirs = _note(game, other, "0x001234", "Lives")

    data = _raw(client, RCHEEVOS_CODE_NOTES)

    assert data == {
        **NOT_THE_AUTHOR,
        "SuccessfulAddresses": [0x61994, 0x10],
        "AccessDeniedAddresses": [0x1234],
    }
    theirs.refresh_from_db()
    assert theirs.note == "Lives"
    assert CodeNote.objects.filter(address="0x10", author=player).exists()


@pytest.mark.django_db
def test_submitcodenotes_lets_staff_rewrite_the_notes_of_others(client, staff, other, game):
    theirs = _note(game, other, "0x1234", "Lives")
    body = _with(RCHEEVOS_CODE_NOTES, u=STAFF, t=STAFF_TOKEN, n="4660:Lives (1 byte)\n")

    assert _raw(client, body) == {"Success": True, "SuccessfulAddresses": [0x1234]}
    theirs.refresh_from_db()
    assert (theirs.note, theirs.author) == ("Lives (1 byte)", staff)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("notes", "error"),
    [
        ("4660 Lives\n", "Improperly encoded notes list."),
        ("0x1234:Lives\n", "Improperly encoded notes list."),
        ("4660:Lives\\q\n", "Improperly encoded notes list."),
        ("4660:Lives\\\n", "Improperly encoded notes list."),
        (
            "".join(f"{address}:n\n" for address in range(MAX_CODE_NOTES_PER_REQUEST + 1)),
            "Too many notes in a single request.",
        ),
    ],
)
def test_submitcodenotes_rejects_a_malformed_list(client, player, game, notes, error):
    data = _post(client, r="submitcodenotes", u=PLAYER, t=PLAYER_TOKEN, g=GAME_ID, n=notes)

    assert data == _invalid(error)
    assert not CodeNote.objects.exists()


@pytest.mark.django_db
def test_submitcodenote_deletes_its_authors_note(client, player, game):
    _note(game, player, "0x1234", "Lives")

    assert _raw(client, RCHEEVOS_DELETE_CODE_NOTE) == {"Success": True}
    assert not CodeNote.objects.exists()


@pytest.mark.django_db
def test_submitcodenote_adds_a_note(client, player, game):
    data = _post(client, r="submitcodenote", u=PLAYER, t=PLAYER_TOKEN, g=GAME_ID, m=4660, n="x")

    assert data == {"Success": True}
    assert CodeNote.objects.get().address == "0x1234"


@pytest.mark.django_db
def test_submitcodenote_cannot_delete_the_note_of_another(client, player, other, game):
    _note(game, other, "0x1234", "Lives")

    assert _raw(client, RCHEEVOS_DELETE_CODE_NOTE) == NOT_THE_AUTHOR
    assert CodeNote.objects.exists()


@pytest.mark.django_db
def test_submitcodenote_unknown_game(client, player, game):
    data = _raw(client, _with(RCHEEVOS_DELETE_CODE_NOTE, g=str(GAME_ID + 1)))

    assert data == _not_found("game")


# --- submitrichpresence ---

RICH_PRESENCE = "Display:\nIn a stage"


@pytest.mark.django_db
def test_submitrichpresence_lets_staff_set_the_script(client, staff, game):
    data = _post(client, r="submitrichpresence", u=STAFF, t=STAFF_TOKEN, g=GAME_ID, d=RICH_PRESENCE)

    assert data == {"Success": True}
    game.refresh_from_db()
    assert game.rich_presence_patch == RICH_PRESENCE


@pytest.mark.django_db
def test_submitrichpresence_is_staff_only(client, player, game):
    data = _post(
        client, r="submitrichpresence", u=PLAYER, t=PLAYER_TOKEN, g=GAME_ID, d=RICH_PRESENCE
    )

    assert data == STAFF_ONLY
    game.refresh_from_db()
    assert game.rich_presence_patch == ""


@pytest.mark.django_db
def test_submitrichpresence_unknown_game_or_missing_script(client, staff, game):
    unknown = _post(client, r="submitrichpresence", u=STAFF, t=STAFF_TOKEN, g=GAME_ID + 1, d="x")
    missing = _post(client, r="submitrichpresence", u=STAFF, t=STAFF_TOKEN, g=GAME_ID)

    assert unknown == _not_found("game")
    assert missing == MISSING_PARAMETER


# --- submitgametitle ---


def _game_response(game_id):
    return {"Success": True, "GameID": game_id, "Response": {"GameID": game_id}}


@pytest.mark.django_db
def test_submitgametitle_creates_the_game_and_links_the_hash(client, staff, console):
    data = _raw(client, RCHEEVOS_GAME_HASH)

    game = Game.objects.get(title="Crash")
    assert data == _game_response(game.pk)
    assert game.console == console
    game_hash = GameHash.objects.get(md5=RCHEEVOS_GAME_HASH_MD5)
    assert (game_hash.game, game_hash.label) == (game, "USA")


@pytest.mark.django_db
def test_submitgametitle_links_the_hash_to_the_game_named(client, staff, game):
    data = _raw(client, _with(RCHEEVOS_GAME_HASH, g=str(GAME_ID), i=""))

    assert data == _game_response(GAME_ID)
    assert GameHash.objects.get().game == game


@pytest.mark.django_db
def test_submitgametitle_reuses_the_game_with_that_title(client, staff, console):
    existing = Game.objects.create(title="Crash", console=console)

    assert _raw(client, RCHEEVOS_GAME_HASH) == _game_response(existing.pk)
    assert Game.objects.count() == 1


@pytest.mark.django_db
def test_submitgametitle_again_for_the_same_game_changes_nothing(client, staff, console):
    first = _raw(client, RCHEEVOS_GAME_HASH)

    assert _raw(client, RCHEEVOS_GAME_HASH) == first
    assert GameHash.objects.count() == 1


@pytest.mark.django_db
def test_submitgametitle_refuses_a_hash_of_another_game(client, staff, game):
    GameHash.objects.create(game=game, md5=RCHEEVOS_GAME_HASH_MD5, label="USA")

    data = _raw(client, RCHEEVOS_GAME_HASH)

    assert data == _invalid(f"The hash is already linked to game {GAME_ID}.")
    assert not Game.objects.filter(title="Crash").exists()


@pytest.mark.django_db
def test_submitgametitle_is_staff_only(client, player, console):
    data = _raw(client, _with(RCHEEVOS_GAME_HASH, u=PLAYER, t=PLAYER_TOKEN))

    assert data == STAFF_ONLY
    assert not Game.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"m": "abc"}, "Hash must be 32 hexadecimal characters."),
        ({"m": "z" * 32}, "Hash must be 32 hexadecimal characters."),
        ({"i": "C"}, "Title must be at least 2 characters long."),
        ({"c": "99"}, "Unknown system ID."),
    ],
)
def test_submitgametitle_rejects_invalid_values(client, staff, console, changes, error):
    assert _raw(client, _with(RCHEEVOS_GAME_HASH, **changes)) == _invalid(error)
    assert not GameHash.objects.exists()


# --- Badges ---


@pytest.mark.django_db
def test_badgeiter_without_badges_starts_at_one(client):
    assert _post(client, r="badgeiter") == {"Success": True, "FirstBadge": 1, "NextBadge": 1}


@pytest.mark.django_db
def test_badgeiter_spans_the_uploaded_badges(client, db):
    older, newer = (
        Badge.objects.create(image=SimpleUploadedFile(name, _png())) for name in ("o.png", "n.png")
    )

    data = _post(client, r="badgeiter")

    assert data == {"Success": True, "FirstBadge": older.pk, "NextBadge": newer.pk + 1}


def _upload(client, filename, content, **params):
    upload = SimpleUploadedFile(filename, content)
    return client.post("/doupload.php", {"u": PLAYER, "t": PLAYER_TOKEN, "file": upload, **params})


@pytest.mark.django_db
@pytest.mark.parametrize(("extension", "image_format"), [("png", "PNG"), ("gif", "GIF")])
def test_uploadbadgeimage_names_the_upload_after_the_next_badge(
    client, player, extension, image_format
):
    response = _upload(client, f"uploadbadgeimage.{extension}", _png(image_format=image_format))

    badge = Badge.objects.get()
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"Success": True, "Response": {"BadgeIter": badge.name}}
    assert badge.uploaded_by == player
    assert client.get(f"/Badge/{badge.name}.png").status_code == HTTPStatus.OK
    assert client.get(f"/Badge/{badge.name}_lock.png").status_code == HTTPStatus.OK


@pytest.mark.django_db
def test_uploaded_badge_can_be_given_to_an_achievement(client, player, game):
    badge_name = _upload(client, "uploadbadgeimage.jpg", _png(image_format="JPEG")).json()[
        "Response"
    ]["BadgeIter"]

    data = _post(client, **_signed_achievement(PLAYER, PLAYER_TOKEN, b=badge_name))

    assert data["Success"] is True
    assert Achievement.objects.get().badge_name == badge_name


@pytest.mark.django_db
def test_uploadbadgeimage_accepts_r_with_any_file_name(client, player):
    response = _upload(client, "badge.png", _png(), r="uploadbadgeimage")

    assert response.json()["Success"] is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("content", "error"),
    [
        (b"not an image", "Upload a PNG, JPEG or GIF image."),
        (_png(image_format="BMP"), "Upload a PNG, JPEG or GIF image."),
        (_truncated("PNG"), "Upload a PNG, JPEG or GIF image."),
        (_truncated("JPEG"), "Upload a PNG, JPEG or GIF image."),
        (_truncated("GIF"), "Upload a PNG, JPEG or GIF image."),
        (
            b"0" * (MAX_BADGE_UPLOAD_BYTES + 1),
            f"The badge image must be at most {MAX_BADGE_UPLOAD_BYTES} bytes.",
        ),
    ],
)
def test_uploadbadgeimage_rejects_other_files(client, player, content, error):
    assert _upload(client, "uploadbadgeimage.png", content).json() == _invalid(error)
    assert not Badge.objects.exists()


@pytest.mark.django_db
def test_uploadbadgeimage_needs_a_file_and_credentials(client, player):
    no_file = client.post(
        "/doupload.php", {"r": "uploadbadgeimage", "u": PLAYER, "t": PLAYER_TOKEN}
    )
    bad_token = _upload(client, "uploadbadgeimage.png", _png(), t="wrong")

    assert no_file.json() == MISSING_PARAMETER
    assert bad_token.json() == INVALID_CREDENTIALS
    assert not Badge.objects.exists()


@pytest.mark.django_db
def test_doupload_rejects_other_uploads(client, player):
    data = _upload(client, "uploadavatar.png", _png()).json()

    assert data == {"Success": False, "Error": "Unknown action: uploadavatar"}


# --- achievementwondata ---


@pytest.fixture
def won_achievement(game, player, other, staff):
    """Unlocked in softcore by `player`, then in both modes by `other`, then by `staff`."""
    achievement = _achievement(game, player, pk=WON_ACHIEVEMENT_ID)
    now = timezone.now()
    for minutes_ago, user, hardcore in (
        (30, player, False),
        (20, other, False),
        (10, other, True),
        (5, staff, False),
    ):
        UserUnlock.objects.create(
            user=user,
            achievement=achievement,
            hardcore=hardcore,
            unlocked_at=now - timedelta(minutes=minutes_ago),
        )
    for user in (player, other, staff):
        PlayerGame.objects.create(user=user, game=game)
    PlayerGame.objects.create(user=_user("idle", "idle-tok"), game=game)
    return achievement


def _winner(user, achievement, hardcore):
    unlock = UserUnlock.objects.get(user=user, achievement=achievement, hardcore=hardcore)
    return {
        "User": user.username,
        "DateAwarded": int(unlock.unlocked_at.timestamp()),
        "AvatarUrl": f"http://testserver{avatar_path(user.username)}",
    }


@pytest.mark.django_db
def test_achievementwondata_lists_the_latest_winners(client, player, other, staff, won_achievement):
    data = _raw(client, _with(RCHEEVOS_ACHIEVEMENT_WON_DATA, f="0", o="0"))

    assert data == {
        "Success": True,
        "AchievementID": won_achievement.pk,
        "Response": {
            "NumEarned": 3,
            "TotalPlayers": 4,
            "GameID": GAME_ID,
            "RecentWinner": [
                _winner(staff, won_achievement, hardcore=False),
                _winner(other, won_achievement, hardcore=True),
                _winner(player, won_achievement, hardcore=False),
            ],
        },
    }


@pytest.mark.django_db
def test_achievementwondata_pages_by_o_and_c(client, player, won_achievement):
    data = _post(
        client, r="achievementwondata", u=PLAYER, t=PLAYER_TOKEN, a=WON_ACHIEVEMENT_ID, o=1, c=1
    )

    assert [winner["User"] for winner in data["Response"]["RecentWinner"]] == [OTHER]


@pytest.mark.django_db
def test_achievementwondata_friends_only_is_empty(client, won_achievement):
    data = _raw(client, RCHEEVOS_ACHIEVEMENT_WON_DATA)

    assert data["Response"]["RecentWinner"] == []
    assert data["Response"]["NumEarned"] == 3


@pytest.mark.django_db
def test_achievementwondata_hides_unknown_and_other_users_drafts(client, player, other, game):
    draft = _achievement(game, other, status=Achievement.STATUS_DRAFT)

    for achievement_id in (draft.pk, draft.pk + 1):
        data = _post(client, r="achievementwondata", u=PLAYER, t=PLAYER_TOKEN, a=achievement_id)
        assert data == _not_found("achievement")


@pytest.mark.django_db
def test_achievementwondata_defaults_to_a_page_of_ten(client, player, game):
    achievement = _achievement(game, player)
    for index in range(ACHIEVEMENTWONDATA_DEFAULT_COUNT + 1):
        UserUnlock.objects.create(user=_user(f"p{index}", f"t{index}"), achievement=achievement)

    data = _post(client, r="achievementwondata", u=PLAYER, t=PLAYER_TOKEN, a=achievement.pk)

    assert len(data["Response"]["RecentWinner"]) == ACHIEVEMENTWONDATA_DEFAULT_COUNT


# --- latestclient ---


@pytest.mark.django_db
def test_latestclient_lets_every_emulator_through(client):
    assert _post(client, r="latestclient", e=7) == _not_found("client")
    assert _post(client, r="latestclient") == MISSING_PARAMETER


# --- Authentication ---

AUTHENTICATED_EDITOR_ACTIONS = (
    "submitcodenote",
    "submitcodenotes",
    "uploadachievement",
    "uploadleaderboard",
    "submitrichpresence",
    "submitgametitle",
    "achievementwondata",
)


@pytest.mark.django_db
@pytest.mark.parametrize("action", AUTHENTICATED_EDITOR_ACTIONS)
def test_editor_actions_need_a_valid_token(client, player, action):
    assert _post(client, r=action, u=PLAYER, t="wrong") == INVALID_CREDENTIALS
