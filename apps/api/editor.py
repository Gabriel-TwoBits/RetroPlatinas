"""The dorequest and doupload actions RAIntegration writes a set with: code notes, achievements,
leaderboards, rich presence, badges and hashes (`rc_api_editor.c`)."""

import logging
import re
from http import HTTPStatus

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Min
from django.utils import translation

from apps.achievements.models import (
    BADGE_NAME_MAX_CHARS,
    PLACEHOLDER_BADGE_NAME,
    Achievement,
    Badge,
    CodeNote,
    is_known_badge_name,
    validate_badge_image,
)
from apps.achievements.scoring import recalculate_unlocker_points
from apps.anticheat.detection import _md5_hex, signature_matches
from apps.api.handlers import (
    _ACHIEVEMENT_NOT_FOUND,
    _GAME_NOT_FOUND,
    _MISSING_PARAMETER,
    ACHIEVEMENT_FLAGS_CORE,
    ACHIEVEMENT_FLAGS_UNOFFICIAL,
    _achievements_visible_to,
    _authenticate,
    _flag_param,
    _invalid_parameter,
    _is_uint32,
    _not_found,
    _uint_param,
)
from apps.games.models import LOWERCASE_HEX, MD5_HEX_DIGITS, Console, Game, GameHash
from apps.leaderboards.models import Leaderboard

logger = logging.getLogger("apps.api")


def _access_denied(message="Access denied."):
    return {
        "Success": False,
        "Error": message,
        "Status": HTTPStatus.FORBIDDEN,
        "Code": "access_denied",
    }


_INVALID_CHECKSUM = _access_denied("Invalid checksum.")
_STAFF_ONLY = _access_denied("Only staff can perform this action.")
_NOT_THE_AUTHOR = _access_denied("Only the author or staff can change this.")


def _can_edit(user, author_id):
    return user.is_staff or author_id == user.pk


def _text_param(request, name, *, required=True, max_length=None):
    """`(value, None)` for a text parameter, else `(None, error)`.

    A required parameter must be sent and not be empty; an optional one defaults to "".
    """
    value = request.POST.get(name, "")
    if value == "" and required:
        return None, _MISSING_PARAMETER
    elif max_length is not None and len(value) > max_length:
        return None, _invalid_parameter(f"Invalid {name}: at most {max_length} characters.")
    else:
        return value, None


def _checksum_error(request, expected):
    """`None` when `h` is `expected`, else the protocol error."""
    received = request.POST.get("h", "")
    if received == "":
        return _MISSING_PARAMETER
    elif signature_matches(expected, received.lower()):
        return None
    else:
        return _INVALID_CHECKSUM


def _game(game_id):
    return Game.objects.filter(pk=game_id).first()


# --- Code notes ---

# RAWeb's cap on the notes one submitcodenotes may carry.
MAX_CODE_NOTES_PER_REQUEST = 500
# rcheevos escapes a note's backslashes and newlines, since a newline ends each note's line.
CODE_NOTE_ESCAPE = re.compile(r"\\(.?)", re.DOTALL)
CODE_NOTE_ESCAPES = {"\\": "\\", "r": "\r", "n": "\n"}
CODE_NOTE_LINE_SEPARATOR = "\n"
CODE_NOTE_ADDRESS_SEPARATOR = ":"
HEX_BASE = 16
# RA serves code note addresses as `0x%06x`.
CODE_NOTE_ADDRESS_HEX_DIGITS = 6


def _served_address(address):
    """The address as RA serves it, which rcheevos reads back as hex."""
    return f"0x{address:0{CODE_NOTE_ADDRESS_HEX_DIGITS}x}"


def _stored_address(address):
    return f"0x{address:x}"


def _parsed_address(note):
    """The note's address as a number, else `None`: the column is free text, typed in the admin."""
    try:
        address = int(note.address, HEX_BASE)
    except ValueError:
        address = None
    if address is None or address < 0:
        logger.warning("Code note %s has no hex address: %r", note.pk, note.address)
        return None
    else:
        return address


def _code_notes_by_address(game):
    """The game's notes by address; the text column holds hex addresses in any padding.

    A note whose address does not parse is left out rather than failing the whole game.
    """
    # TRADEOFF: parsed in Python because `address` is text; an integer column makes it a query.
    notes = CodeNote.objects.filter(game=game).select_related("author").order_by("id")
    by_address = {}
    for note in notes:
        address = _parsed_address(note)
        if address is not None:
            by_address[address] = note
        else:
            continue
    return by_address


def _save_code_notes(user, game, notes):
    """Writes `{address: text}`, an empty text deleting the note, as far as `user` may.

    Returns the addresses written and the addresses refused: anyone may add a note, only its
    author or staff may change or delete it.
    """
    successful = []
    denied = []
    with transaction.atomic():
        # Serializes writers per game, so two adds of one new address cannot both insert it.
        Game.objects.select_for_update().get(pk=game.pk)
        existing = _code_notes_by_address(game)
        for address, text in notes.items():
            note = existing.get(address)
            if note is None and text == "":
                successful.append(address)
            elif note is None:
                CodeNote.objects.create(
                    game=game, author=user, address=_stored_address(address), note=text
                )
                successful.append(address)
            elif not _can_edit(user, note.author_id):
                denied.append(address)
            elif text == "":
                note.delete()
                successful.append(address)
            else:
                # As on RA, a note is credited to whoever wrote its current text.
                note.author = user
                note.note = text
                note.save(update_fields=["author", "note", "updated_at"])
                successful.append(address)
    return successful, denied


def handle_codenotes2(request):
    game_id, error = _uint_param(request, "g")
    if error is not None:
        return error
    game = _game(game_id)
    if game is None:
        return _GAME_NOT_FOUND

    notes = sorted(_code_notes_by_address(game).items())
    return {
        "Success": True,
        "CodeNotes": [
            {"User": note.author.username, "Address": _served_address(address), "Note": note.note}
            # rcheevos reads an empty note as a deleted one.
            for address, note in notes
            if note.note
        ],
    }


def handle_submitcodenote(request):
    user, error = _authenticate(request)
    if error is not None:
        return error
    game_id, error = _uint_param(request, "g")
    if error is not None:
        return error
    address, error = _uint_param(request, "m")
    if error is not None:
        return error
    game = _game(game_id)
    if game is None:
        return _GAME_NOT_FOUND

    # rcheevos omits `n` to delete the note.
    _, denied = _save_code_notes(user, game, {address: request.POST.get("n", "")})
    if denied:
        return _NOT_THE_AUTHOR
    else:
        return {"Success": True}


def _unescape_code_note(escaped):
    def unescape(match):
        escape = match.group(1)
        if escape in CODE_NOTE_ESCAPES:
            return CODE_NOTE_ESCAPES[escape]
        else:
            raise ValueError(f"unknown escape \\{escape}")

    return CODE_NOTE_ESCAPE.sub(unescape, escaped)


def _parse_code_note_lines(raw):
    """`({address: text}, None)` from rcheevos' `<decimal address>:<escaped note>` lines, else
    `(None, error)`; a later line for an address replaces an earlier one."""
    notes = {}
    for line in raw.split(CODE_NOTE_LINE_SEPARATOR):
        if line == "":
            continue
        raw_address, separator, escaped = line.partition(CODE_NOTE_ADDRESS_SEPARATOR)
        if not separator or not _is_uint32(raw_address):
            return None, _invalid_parameter("Improperly encoded notes list.")
        try:
            notes[int(raw_address)] = _unescape_code_note(escaped)
        except ValueError:
            return None, _invalid_parameter("Improperly encoded notes list.")
        if len(notes) > MAX_CODE_NOTES_PER_REQUEST:
            return None, _invalid_parameter("Too many notes in a single request.")
    return notes, None


def handle_submitcodenotes(request):
    user, error = _authenticate(request)
    if error is not None:
        return error
    game_id, error = _uint_param(request, "g")
    if error is not None:
        return error
    raw_notes = request.POST.get("n")
    if raw_notes is None:
        return _MISSING_PARAMETER
    notes, error = _parse_code_note_lines(raw_notes)
    if error is not None:
        return error
    game = _game(game_id)
    if game is None:
        return _GAME_NOT_FOUND

    successful, denied = _save_code_notes(user, game, notes)
    if denied:
        # rcheevos reads both lists alongside `access_denied`.
        return {
            **_NOT_THE_AUTHOR,
            "SuccessfulAddresses": successful,
            "AccessDeniedAddresses": denied,
        }
    else:
        return {"Success": True, "SuccessfulAddresses": successful}


# --- Achievements ---

# rcheevos signs points * 3 into the uploadachievement checksum.
CHECKSUM_POINTS_MULTIPLIER = 3
# The point values RAWeb accepts (`AchievementPoints`), the ones RAIntegration offers.
ACHIEVEMENT_POINT_VALUES = frozenset({0, 1, 2, 3, 4, 5, 10, 25, 50, 100})
# The category RAIntegration files the achievement under; publishing happens on the site only.
UPLOAD_CATEGORIES = frozenset({ACHIEVEMENT_FLAGS_CORE, ACHIEVEMENT_FLAGS_UNOFFICIAL})
ACHIEVEMENT_TYPES = frozenset(value for value, _ in Achievement.TYPE_CHOICES)
ACHIEVEMENT_TITLE_MAX_LENGTH = Achievement._meta.get_field("title").max_length


def achievement_upload_checksum(username, achievement_id, trigger, points):
    """The `h` rcheevos signs an uploadachievement with
    (`rc_api_init_update_achievement_request`); `achievement_id` is 0 for a new one."""
    scaled_points = points * CHECKSUM_POINTS_MULTIPLIER
    return _md5_hex(f"{username}SECRET{achievement_id}SEC{trigger}{points}RE2{scaled_points}")


def _achievement_upload(request):
    """`(fields, None)` with the uploaded achievement's fields, else `(None, error)`.

    `fields["type"]` is `None` when `x` is absent, which leaves an existing type unchanged.
    """
    fields = {}
    for name, field, max_length in (
        ("n", "title", ACHIEVEMENT_TITLE_MAX_LENGTH),
        ("d", "description", None),
        ("m", "mem_addr", None),
        ("b", "badge_name", BADGE_NAME_MAX_CHARS),
    ):
        fields[field], error = _text_param(request, name, max_length=max_length)
        if error is not None:
            return None, error
    for name, field in (("z", "points"), ("f", "category")):
        fields[field], error = _uint_param(request, name)
        if error is not None:
            return None, error
    fields["type"] = request.POST.get("x")
    return fields, None


def _achievement_upload_error(fields):
    """The error for a value RAIntegration may not set, else `None`; points are checked only
    when they change."""
    if fields["category"] not in UPLOAD_CATEGORIES:
        return _invalid_parameter(f"Unknown flag: {fields['category']}.")
    elif fields["type"] is not None and fields["type"] not in ACHIEVEMENT_TYPES:
        return _invalid_parameter(f"Unknown type: {fields['type']}.")
    elif not is_known_badge_name(fields["badge_name"]):
        return _invalid_parameter(
            f"Unknown badge: {fields['badge_name']}. Upload it first, or use "
            f"{PLACEHOLDER_BADGE_NAME}."
        )
    else:
        return None


def _invalid_points(points):
    return _invalid_parameter(f"Invalid points value: {points}.")


def _create_achievement(user, game_id, fields):
    if game_id == 0:
        return _MISSING_PARAMETER
    if fields["points"] not in ACHIEVEMENT_POINT_VALUES:
        return _invalid_points(fields["points"])
    game = _game(game_id)
    if game is None:
        return _GAME_NOT_FOUND
    # New achievements are drafts whatever `f` asks: only the site publishes them.
    achievement = Achievement.objects.create(
        game=game,
        author=user,
        status=Achievement.STATUS_DRAFT,
        title=fields["title"],
        description=fields["description"],
        mem_addr=fields["mem_addr"],
        points=fields["points"],
        badge_name=fields["badge_name"],
        type=fields["type"] or Achievement.TYPE_NONE,
    )
    return {"Success": True, "AchievementID": achievement.pk}


def _update_achievement(user, achievement_id, game_id, fields):
    # Only staff see other users' drafts; to anyone else they do not exist.
    if user.is_staff:
        editable = Achievement.objects.all()
    else:
        editable = _achievements_visible_to(user)
    with transaction.atomic():
        achievement = editable.filter(pk=achievement_id).first()
        if achievement is None:
            return _ACHIEVEMENT_NOT_FOUND
        elif game_id not in (0, achievement.game_id):
            return _invalid_parameter("Invalid g: the achievement belongs to another game.")
        elif not _can_edit(user, achievement.author_id):
            return _NOT_THE_AUTHOR
        elif (
            achievement.points != fields["points"]
            and fields["points"] not in ACHIEVEMENT_POINT_VALUES
        ):
            # Unchanged points pass as they are, even a value the admin set outside RA's scale.
            return _invalid_points(fields["points"])
        else:
            points_changed = achievement.points != fields["points"]
            achievement.title = fields["title"]
            achievement.description = fields["description"]
            achievement.mem_addr = fields["mem_addr"]
            achievement.points = fields["points"]
            achievement.badge_name = fields["badge_name"]
            if fields["type"] is not None:
                achievement.type = fields["type"]
            # The status stays: `f` never publishes or unpublishes.
            achievement.save()
            if points_changed and achievement.status in Achievement.PUBLISHED_STATUSES:
                recalculate_unlocker_points([achievement.pk])
            return {"Success": True, "AchievementID": achievement.pk}


def handle_uploadachievement(request):
    user, error = _authenticate(request)
    if error is not None:
        return error
    achievement_id, error = _uint_param(request, "a", default=0)
    if error is not None:
        return error
    game_id, error = _uint_param(request, "g", default=0)
    if error is not None:
        return error
    fields, error = _achievement_upload(request)
    if error is not None:
        return error
    error = _checksum_error(
        request,
        achievement_upload_checksum(
            user.username, achievement_id, fields["mem_addr"], fields["points"]
        ),
    )
    if error is not None:
        return error
    error = _achievement_upload_error(fields)
    if error is not None:
        return error

    if achievement_id == 0:
        return _create_achievement(user, game_id, fields)
    else:
        return _update_achievement(user, achievement_id, game_id, fields)


# --- Leaderboards ---

LEADERBOARD_TITLE_MAX_LENGTH = Leaderboard._meta.get_field("title").max_length


def leaderboard_upload_checksum(username, leaderboard_id, start, submit, cancel, value, fmt):
    """The `h` rcheevos signs an uploadleaderboard with
    (`rc_api_init_update_leaderboard_request`); `leaderboard_id` is 0 for a new one."""
    return _md5_hex(f"{username}SECRET{leaderboard_id}SEC{start}{submit}{cancel}{value}RE2{fmt}")


def leaderboard_mem(start, submit, cancel, value):
    """The leaderboard definition rcheevos parses from its four parts, as RAWeb stores it."""
    return f"STA:{start}::CAN:{cancel}::SUB:{submit}::VAL:{value}"


def _leaderboard_upload(request):
    """`(fields, None)` with the uploaded leaderboard's fields, else `(None, error)`."""
    fields = {}
    for name, field, required, max_length in (
        ("n", "title", True, LEADERBOARD_TITLE_MAX_LENGTH),
        ("d", "description", False, None),
        ("s", "start", True, None),
        ("b", "submit", True, None),
        ("c", "cancel", True, None),
        ("l", "value", True, None),
        ("f", "format", True, None),
    ):
        fields[field], error = _text_param(request, name, required=required, max_length=max_length)
        if error is not None:
            return None, error
    fields["lower_is_better"], error = _flag_param(request, "w")
    if error is not None:
        return None, error
    elif fields["lower_is_better"] is None:
        return None, _MISSING_PARAMETER
    else:
        return fields, None


def _save_leaderboard(leaderboard, fields, value_format):
    leaderboard.title = fields["title"]
    leaderboard.description = fields["description"]
    leaderboard.mem_addr = leaderboard_mem(
        fields["start"], fields["submit"], fields["cancel"], fields["value"]
    )
    leaderboard.format = value_format
    leaderboard.lower_is_better = fields["lower_is_better"]
    leaderboard.save()
    return {"Success": True, "LeaderboardID": leaderboard.pk}


def handle_uploadleaderboard(request):
    user, error = _authenticate(request)
    if error is not None:
        return error
    leaderboard_id, error = _uint_param(request, "i", default=0)
    if error is not None:
        return error
    game_id, error = _uint_param(request, "g", default=0)
    if error is not None:
        return error
    fields, error = _leaderboard_upload(request)
    if error is not None:
        return error
    expected = leaderboard_upload_checksum(
        user.username,
        leaderboard_id,
        fields["start"],
        fields["submit"],
        fields["cancel"],
        fields["value"],
        fields["format"],
    )
    error = _checksum_error(request, expected)
    if error is not None:
        return error
    value_format = Leaderboard.canonical_format(fields["format"])
    if value_format is None:
        return _invalid_parameter(f"Unknown format: {fields['format']}.")

    if leaderboard_id == 0 and game_id == 0:
        return _MISSING_PARAMETER
    elif leaderboard_id == 0 and not user.is_staff:
        # A leaderboard has no draft state: a new one reaches every player at once.
        return _STAFF_ONLY
    elif leaderboard_id == 0:
        game = _game(game_id)
        if game is None:
            return _GAME_NOT_FOUND
        return _save_leaderboard(Leaderboard(game=game, author=user), fields, value_format)
    else:
        leaderboard = Leaderboard.objects.filter(pk=leaderboard_id).first()
        if leaderboard is None:
            return _not_found("leaderboard")
        elif game_id not in (0, leaderboard.game_id):
            return _invalid_parameter("Invalid g: the leaderboard belongs to another game.")
        elif not _can_edit(user, leaderboard.author_id):
            return _NOT_THE_AUTHOR
        else:
            return _save_leaderboard(leaderboard, fields, value_format)


# --- Games ---


def handle_submitrichpresence(request):
    user, error = _authenticate(request)
    if error is not None:
        return error
    game_id, error = _uint_param(request, "g")
    if error is not None:
        return error
    script = request.POST.get("d")
    if script is None:
        return _MISSING_PARAMETER
    if not user.is_staff:
        return _STAFF_ONLY
    game = _game(game_id)
    if game is None:
        return _GAME_NOT_FOUND

    game.rich_presence_patch = script
    game.save(update_fields=["rich_presence_patch"])
    return {"Success": True}


# RAWeb's shortest game title.
MIN_GAME_TITLE_LENGTH = 2
GAME_TITLE_MAX_LENGTH = Game._meta.get_field("title").max_length
HASH_LABEL_MAX_LENGTH = GameHash._meta.get_field("label").max_length


def _game_for_new_hash(game_id, console_id, title):
    """`(game, None)`: the game `g` names, else the one titled `title` on the console, created
    when there is none; `(None, error)` when `g` or the console is unknown."""
    if game_id:
        game = _game(game_id)
        if game is None:
            return None, _GAME_NOT_FOUND
        else:
            return game, None
    console = Console.objects.filter(ra_id=console_id).first()
    if console is None:
        return None, _invalid_parameter("Unknown system ID.")
    game = Game.objects.filter(console=console, title=title).order_by("id").first()
    if game is None:
        game = Game.objects.create(console=console, title=title)
    return game, None


def _game_title_error(md5, title, game_id):
    if len(md5) != MD5_HEX_DIGITS or not LOWERCASE_HEX.fullmatch(md5):
        return _invalid_parameter(f"Hash must be {MD5_HEX_DIGITS} hexadecimal characters.")
    elif game_id == 0 and len(title) < MIN_GAME_TITLE_LENGTH:
        return _invalid_parameter(
            f"Title must be at least {MIN_GAME_TITLE_LENGTH} characters long."
        )
    else:
        return None


def handle_submitgametitle(request):
    user, error = _authenticate(request)
    if error is not None:
        return error
    md5, error = _text_param(request, "m")
    if error is not None:
        return error
    title, error = _text_param(request, "i", required=False, max_length=GAME_TITLE_MAX_LENGTH)
    if error is not None:
        return error
    label, error = _text_param(request, "d", required=False, max_length=HASH_LABEL_MAX_LENGTH)
    if error is not None:
        return error
    console_id, error = _uint_param(request, "c")
    if error is not None:
        return error
    game_id, error = _uint_param(request, "g", default=0)
    if error is not None:
        return error
    md5 = md5.lower()
    error = _game_title_error(md5, title, game_id)
    if error is not None:
        return error
    if not user.is_staff:
        return _STAFF_ONLY

    with transaction.atomic():
        game, error = _game_for_new_hash(game_id, console_id, title)
        if error is not None:
            return error
        linked = GameHash.objects.filter(md5=md5).first()
        if linked is None:
            # A title may be longer than a label can hold.
            label = label or game.title[:HASH_LABEL_MAX_LENGTH]
            GameHash.objects.create(game=game, md5=md5, label=label)
        elif linked.game_id != game.pk:
            # Undoes the game just created for the title, if any.
            transaction.set_rollback(True)
            return _invalid_parameter(f"The hash is already linked to game {linked.game_id}.")
        else:
            # Already linked to this game: linking it again changes nothing.
            pass
    # rcheevos reads the nested GameID; RAWeb repeats it at the top level.
    return {"Success": True, "GameID": game.pk, "Response": {"GameID": game.pk}}


# --- Badges ---

# RA reserves 00000 for the placeholder, so uploads are numbered from 1.
FIRST_BADGE_NUMBER = 1


def handle_badgeiter(request):
    numbers = Badge.objects.aggregate(first=Min("pk"), last=Max("pk"))
    first = numbers["first"] if numbers["first"] is not None else FIRST_BADGE_NUMBER
    last = numbers["last"] if numbers["last"] is not None else int(PLACEHOLDER_BADGE_NAME)
    return {"Success": True, "FirstBadge": first, "NextBadge": last + 1}


def handle_uploadbadgeimage(request):
    user, error = _authenticate(request)
    if error is not None:
        return error
    upload = request.FILES.get("file")
    if upload is None:
        return _MISSING_PARAMETER
    # The protocol's errors are English, whatever the site's language.
    with translation.override("en"):
        try:
            validate_badge_image(upload)
        except ValidationError as invalid:
            return _invalid_parameter(" ".join(invalid.messages))

    badge = Badge.objects.create(image=upload, uploaded_by=user)
    return {"Success": True, "Response": {"BadgeIter": badge.name}}


EDITOR_HANDLERS = {
    "codenotes2": handle_codenotes2,
    "submitcodenote": handle_submitcodenote,
    "submitcodenotes": handle_submitcodenotes,
    "uploadachievement": handle_uploadachievement,
    "uploadleaderboard": handle_uploadleaderboard,
    "submitrichpresence": handle_submitrichpresence,
    "submitgametitle": handle_submitgametitle,
    "badgeiter": handle_badgeiter,
}
UPLOAD_HANDLERS = {
    "uploadbadgeimage": handle_uploadbadgeimage,
}
