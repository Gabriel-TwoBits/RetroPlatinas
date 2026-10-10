import logging
import re
import secrets
from datetime import UTC, timedelta
from http import HTTPStatus

from django.contrib.auth import authenticate, get_user_model
from django.db import transaction
from django.db.models import Count, F, Min, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounts.models import API_TOKEN_BYTES, Friendship
from apps.achievements.models import Achievement, UserUnlock
from apps.anticheat.detection import (
    award_rate_exceeded,
    award_validation_hash,
    flag_invalid_signature,
    inspect_unlock,
    leaderboard_validation_hash,
    signature_matches,
)
from apps.api.auth import is_expired_token, user_from_token
from apps.core.stats import (
    leaderboard_entries,
    official_achievement_count,
    official_unlocks,
    rank_by_score,
    ranked_entries,
)
from apps.games.models import RICH_PRESENCE_MAX_LENGTH, Console, Game, GameHash, PlayerGame
from apps.games.sets import session_game, sets_for_game, sets_for_hash
from apps.images.catalog import (
    avatar_path,
    badge_path,
    game_icon_path,
    versioned_game_icon_path,
)
from apps.leaderboards.models import Leaderboard, LeaderboardEntry
from apps.notifications.emit import notify_unlock

logger = logging.getLogger("apps.api")


def _not_found(resource):
    return {
        "Success": False,
        "Error": f"Unknown {resource}.",
        "Status": HTTPStatus.NOT_FOUND,
        "Code": "not_found",
    }


_NOT_IMPLEMENTED = {"Success": False, "Error": "not implemented"}
# rcheevos turns these `Code` values into RC_INVALID_CREDENTIALS / RC_EXPIRED_TOKEN;
# a missing or unknown code is only a generic RC_API_FAILURE.
_INVALID_CREDENTIALS = {
    "Success": False,
    "Error": "Credentials invalid.",
    "Status": HTTPStatus.UNAUTHORIZED,
    "Code": "invalid_credentials",
}
_EXPIRED_TOKEN = {
    "Success": False,
    "Error": "The access token has expired. Please log in again.",
    "Status": HTTPStatus.UNAUTHORIZED,
    "Code": "expired_token",
}
_GAME_NOT_FOUND = _not_found("game")
_ACHIEVEMENT_NOT_FOUND = _not_found("achievement")
_MISSING_PARAMETER = {
    "Success": False,
    "Error": "One or more required parameters is missing.",
    "Status": HTTPStatus.UNPROCESSABLE_ENTITY,
    "Code": "missing_parameter",
}
_ACHIEVEMENT_UNOFFICIAL = {
    "Success": False,
    "Error": "Unofficial achievements cannot be unlocked.",
    "Status": HTTPStatus.CONFLICT,
    "Code": "invalid_state",
}
# Sent as the HTTP status too: rc_client retries a 429 with backoff, so the unlock is delayed,
# not lost. rcheevos has no `Code` for it, and reads a missing one as a generic failure.
_TOO_MANY_UNLOCKS = {
    "Success": False,
    "Error": "Too many unlocks at once. The unlock will be retried.",
    "Status": HTTPStatus.TOO_MANY_REQUESTS,
}

# rcheevos RC_ACHIEVEMENT_CATEGORY_CORE / RC_ACHIEVEMENT_CATEGORY_UNOFFICIAL.
ACHIEVEMENT_FLAGS_CORE = 3
ACHIEVEMENT_FLAGS_UNOFFICIAL = 5
# The `Type` rcheevos reads as RC_ACHIEVEMENT_SET_TYPE_CORE; a subset sends its own set type.
SET_TYPE_CORE = "core"

API_TOKEN_LIFETIME = timedelta(days=14)
PERCENT = 100
# rcheevos' JSON parser reads plain decimals only: `1e-05` would not parse.
RARITY_DECIMAL_PLACES = 2


# rcheevos sends every id, offset and count as a uint32.
MAX_UINT32 = 0xFFFFFFFF
# Bounds the digits before `int()`, which rejects strings past Python's digit limit.
UINT32_PATTERN = re.compile(rf"[0-9]{{1,{len(str(MAX_UINT32))}}}")
# rcheevos sends and parses a leaderboard score as an int32.
MIN_INT32 = -(2**31)
MAX_INT32 = 2**31 - 1


def _invalid_parameter(message):
    return {
        "Success": False,
        "Error": message,
        "Status": HTTPStatus.UNPROCESSABLE_ENTITY,
        "Code": "invalid_parameter",
    }


def _flag_param(request, name):
    """`(flag, None)` for a 0/1 parameter, `(None, None)` when absent, else `(None, error)`."""
    raw = request.POST.get(name)
    if raw is None:
        return None, None
    elif raw == "1":
        return True, None
    elif raw == "0":
        return False, None
    else:
        return None, _invalid_parameter(f"Invalid {name}: expected 0 or 1.")


def _is_uint32(raw):
    return UINT32_PATTERN.fullmatch(raw) is not None and int(raw) <= MAX_UINT32


def _uint_param(request, name, default=None):
    """`(value, None)` for a uint32 parameter, else `(None, error)`.

    An absent or empty parameter takes `default`; without one it is a missing parameter.
    """
    raw = request.POST.get(name, "")
    if raw == "" and default is None:
        return None, _MISSING_PARAMETER
    elif raw == "":
        return default, None
    elif _is_uint32(raw):
        return int(raw), None
    else:
        return None, _invalid_parameter(f"Invalid {name}: expected an unsigned integer.")


def _signature_error(request, user, expected, **detail):
    """`None` when `v` is `expected`; else the protocol error, with the attempt flagged."""
    received = request.POST.get("v", "")
    if received == "":
        reason = "missing"
        error = _MISSING_PARAMETER
    elif signature_matches(expected, received):
        return None
    else:
        reason = "mismatch"
        error = _invalid_parameter("Invalid v: the validation hash does not match.")
    flag_invalid_signature(user, request.POST.get("r", ""), reason=reason, **detail)
    return error


# Image URLs are absolute: a missing one makes rcheevos fall back to RetroAchievements' host.
def _user_avatar_url(request, username):
    return request.build_absolute_uri(avatar_path(username))


def _game_icon_url(request, game):
    return request.build_absolute_uri(versioned_game_icon_path(game))


def _authenticate(request):
    """`(user, None)` when `t` is a live token of the user named in `u`, else `(None, error)`."""
    username = request.POST.get("u", "")
    token = request.POST.get("t", "")
    user = user_from_token(token)
    if user is not None and user.username == username:
        return user, None
    elif user is not None:
        return None, _INVALID_CREDENTIALS
    elif is_expired_token(username, token):
        return None, _EXPIRED_TOKEN
    else:
        return None, _INVALID_CREDENTIALS


def handle_login2(request):
    username = request.POST.get("u")
    password = request.POST.get("p")
    if not username:
        return _INVALID_CREDENTIALS
    elif password:
        user = authenticate(username=username, password=password)
        if user is None:
            return _INVALID_CREDENTIALS
    elif request.POST.get("t"):
        user, error = _authenticate(request)
        if error is not None:
            return error
    else:
        return _INVALID_CREDENTIALS
    # Echo the existing valid token instead of rotating: rc_client fires login2
    # twice on connect, and rotating would invalidate the second call's token.
    now = timezone.now()
    if user.api_token and user.api_token_expires_at and user.api_token_expires_at > now:
        token = user.api_token
    else:
        token = secrets.token_hex(API_TOKEN_BYTES)
    user.api_token = token
    user.api_token_expires_at = now + API_TOKEN_LIFETIME
    user.save(update_fields=["api_token", "api_token_expires_at"])
    return {
        "Success": True,
        "User": user.username,
        "Token": token,
        "Score": user.hardcore_points,
        "SoftcoreScore": user.softcore_points,
        "Messages": 0,
        "AccountType": "Registered",
        "AvatarUrl": _user_avatar_url(request, user.username),
    }


def handle_gameid(request):
    md5 = request.POST.get("m", "").lower()
    if not md5:
        return {"Success": True, "GameID": 0}
    game_id = GameHash.objects.filter(md5=md5).values_list("game_id", flat=True).first()
    return {"Success": True, "GameID": game_id if game_id is not None else 0}


def _game_by_id(raw_game_id):
    try:
        game_id = int(raw_game_id)
    except (ValueError, TypeError):
        return None
    return Game.objects.select_related("console").filter(pk=game_id).first()


def _hash_game(md5):
    """The game linked to the hash `md5`, `None` when it is empty or unknown."""
    if md5:
        return (
            Game.objects.select_related("console", "parent_game__console")
            .filter(hashes__md5=md5.lower())
            .first()
        )
    else:
        return None


def _game_from_request(request):
    """The game named by the `m` hash, else by the `g` id; `None` when neither matches."""
    md5 = request.POST.get("m", "")
    game_id_param = request.POST.get("g", "")
    if md5:
        return _hash_game(md5)
    elif game_id_param:
        return _game_by_id(game_id_param)
    else:
        return None


def _served_achievements(game):
    return (
        Achievement.objects.filter(game=game)
        .select_related("author")
        .annotate(
            unlockers=Count("userunlock__user", distinct=True),
            hardcore_unlockers=Count(
                "userunlock__user", filter=Q(userunlock__hardcore=True), distinct=True
            ),
        )
        .order_by("id")
    )


def _player_count(game):
    return PlayerGame.objects.filter(game=game).count()


def _rarity(unlockers, players):
    """Percentage of the game's players who unlocked it, as rcheevos' `Rarity` expects."""
    if players == 0:
        return 0.0
    else:
        return round(unlockers * PERCENT / players, RARITY_DECIMAL_PLACES)


def _achievement_flags(achievement):
    if achievement.status == Achievement.STATUS_OFFICIAL:
        return ACHIEVEMENT_FLAGS_CORE
    elif achievement.status == Achievement.STATUS_UNOFFICIAL:
        return ACHIEVEMENT_FLAGS_UNOFFICIAL
    else:
        raise ValueError(f"Achievement {achievement.pk} has unknown status {achievement.status!r}")


def _serialize_achievement(request, a, players):
    flags = _achievement_flags(a)
    if flags == ACHIEVEMENT_FLAGS_CORE:
        rarity = _rarity(a.unlockers, players)
        rarity_hardcore = _rarity(a.hardcore_unlockers, players)
    else:
        # RA serves 0.0 on unofficial achievements as the signal not to display rarity.
        rarity = rarity_hardcore = 0.0
    return {
        "ID": a.id,
        "MemAddr": a.mem_addr,
        "Title": a.title,
        "Description": a.description,
        "Points": a.points,
        "Author": a.author.username,
        "Modified": int(a.updated_at.timestamp()),
        "Created": int(a.created_at.timestamp()),
        "BadgeName": a.badge_name,
        "BadgeURL": request.build_absolute_uri(badge_path(a.badge_name)),
        "BadgeLockedURL": request.build_absolute_uri(badge_path(a.badge_name, locked=True)),
        "Flags": flags,
        "Type": a.type,
        "Rarity": rarity,
        "RarityHardcore": rarity_hardcore,
    }


def _serialize_leaderboard(lb):
    return {
        "ID": lb.id,
        "Mem": lb.mem_addr,
        "Format": lb.format,
        "LowerIsBetter": lb.lower_is_better,
        "Title": lb.title,
        "Description": lb.description,
        "Hidden": False,
    }


def handle_patch(request):
    user, error = _authenticate(request)
    if error is not None:
        return error

    game = _game_from_request(request)
    if game is None:
        return _GAME_NOT_FOUND

    achievements = _served_achievements(game)
    players = _player_count(game)
    return {
        "Success": True,
        "PatchData": {
            "ID": game.pk,
            "Title": game.title,
            "ConsoleID": game.console.ra_id,
            "ImageIcon": game_icon_path(game),
            "ImageIconURL": _game_icon_url(request, game),
            "RichPresencePatch": game.rich_presence_patch,
            "Achievements": [_serialize_achievement(request, a, players) for a in achievements],
            "Leaderboards": [_serialize_leaderboard(lb) for lb in game.leaderboards.all()],
        },
    }


def _served_sets(request, user):
    """The sets the `m` hash serves `user`, else the `g` game's set alone (the legacy load);
    `None` when neither names a game."""
    md5 = request.POST.get("m", "")
    game_id_param = request.POST.get("g", "")
    if md5:
        hash_game = _hash_game(md5)
        if hash_game is None:
            return None
        else:
            return sets_for_hash(user, hash_game)
    elif game_id_param:
        game = _game_by_id(game_id_param)
        if game is None:
            return None
        else:
            return sets_for_game(game)
    else:
        return None


def _serialize_set(request, served, set_game):
    if set_game.pk == served.core.pk:
        set_type = SET_TYPE_CORE
        # rcheevos titles a set without one after the game.
        title = None
    else:
        set_type = set_game.set_type
        title = set_game.set_title
    achievements = _served_achievements(set_game)
    # Rarity is over the players of the set's own game.
    players = _player_count(set_game)
    return {
        "AchievementSetId": set_game.pk,
        "GameId": set_game.pk,
        "Title": title,
        "Type": set_type,
        "ImageIconUrl": _game_icon_url(request, set_game),
        "Achievements": [_serialize_achievement(request, a, players) for a in achievements],
        "Leaderboards": [_serialize_leaderboard(lb) for lb in set_game.leaderboards.all()],
    }


def handle_achievementsets(request):
    user, error = _authenticate(request)
    if error is not None:
        return error

    served = _served_sets(request, user)
    if served is None:
        logger.info(
            "achievementsets unknown game hash=%s g=%s",
            request.POST.get("m", ""),
            request.POST.get("g", ""),
        )
        return _GAME_NOT_FOUND

    core = served.core
    return {
        "Success": True,
        "GameId": core.pk,
        "Title": core.title,
        "ConsoleId": core.console.ra_id,
        "ImageIconUrl": _game_icon_url(request, core),
        "RichPresenceGameId": served.rich_presence.pk,
        "RichPresencePatch": served.rich_presence.rich_presence_patch,
        "Sets": [_serialize_set(request, served, set_game) for set_game in served.sets],
    }


def handle_allprogress(request):
    user, error = _authenticate(request)
    if error is not None:
        return error
    # TRADEOFF: no per-game progress (an empty map is valid and off the load path);
    # aggregate UserUnlock counts per game when a client needs to show it.
    return {"Success": True, "Response": {}}


def handle_postactivity(request):
    return _NOT_IMPLEMENTED


def _record_session_contact(user, game, hardcore, *, starting=False, rich_presence=""):
    """Marks `user`'s session of `game` live now, as a new session when `starting`, else as a
    ping carrying `rich_presence`; records `hardcore` when sent."""
    now = timezone.now()
    with transaction.atomic():
        player_game, _ = PlayerGame.objects.select_for_update().get_or_create(
            user=user, game=game, defaults={"first_played_at": now, "last_played_at": now}
        )
        if starting:
            player_game.start_session(now)
        else:
            player_game.last_rich_presence = rich_presence
            player_game.record_ping(now)
        if hardcore is not None:
            player_game.hardcore = hardcore
        player_game.save()


def handle_startsession(request):
    user, error = _authenticate(request)
    if error is not None:
        return error

    # rc_client sends `h` only alongside the game hash `m`.
    hardcore, error = _flag_param(request, "h")
    if error is not None:
        return error

    game = _game_by_id(request.POST.get("g", ""))
    if game is None:
        return _GAME_NOT_FOUND
    hash_game = _hash_game(request.POST.get("m", ""))
    # Without a known hash the session is the `g` game's, as on RA.
    if hash_game is None:
        session = game
        served_games = [game]
    else:
        session = session_game(hash_game)
        served_games = sets_for_hash(user, hash_game).sets

    _record_session_contact(user, session, hardcore, starting=True)

    unlocks = UserUnlock.objects.filter(user=user, achievement__game__in=served_games).values(
        "achievement_id", "hardcore", "unlocked_at"
    )

    softcore = []
    hardcore = []
    for unlock in unlocks:
        entry = {
            "ID": unlock["achievement_id"],
            "When": int(unlock["unlocked_at"].timestamp()),
        }
        if unlock["hardcore"]:
            hardcore.append(entry)
        else:
            softcore.append(entry)

    return {
        "Success": True,
        "Unlocks": softcore,
        "HardcoreUnlocks": hardcore,
        "ServerNow": int(timezone.now().timestamp()),
    }


def _remaining_in_set(user, game, hardcore):
    total = official_achievement_count(game)
    unlocked = (
        official_unlocks().filter(user=user, hardcore=hardcore, achievement__game=game).count()
    )
    return max(total - unlocked, 0)


# rc_client retries an unlock until the server takes it, sending `o`, the seconds since the
# unlock; an unlock claimed to be older than this is dated this far back.
UNLOCK_MAX_AGE = timedelta(days=1)


def handle_awardachievement(request):
    user, error = _authenticate(request)
    if error is not None:
        return error

    if award_rate_exceeded(user):
        return _TOO_MANY_UNLOCKS

    try:
        achievement_id = int(request.POST.get("a", ""))
    except (ValueError, TypeError):
        return _ACHIEVEMENT_NOT_FOUND

    hardcore, error = _flag_param(request, "h")
    if error is not None:
        return error
    # An absent `h` is a softcore unlock, signed as `0`.
    hardcore = hardcore is True
    seconds_since_unlock, error = _uint_param(request, "o", default=0)
    if error is not None:
        return error

    expected = award_validation_hash(
        achievement_id, request.POST.get("u", ""), hardcore, seconds_since_unlock
    )
    error = _signature_error(
        request,
        user,
        expected,
        achievement_id=achievement_id,
        hardcore=hardcore,
        seconds_since_unlock=seconds_since_unlock,
    )
    if error is not None:
        return error

    achievement = (
        Achievement.objects.select_related("game", "author").filter(pk=achievement_id).first()
    )
    if achievement is None:
        return _ACHIEVEMENT_NOT_FOUND
    if achievement.status != Achievement.STATUS_OFFICIAL:
        return _ACHIEVEMENT_UNOFFICIAL

    now = timezone.now()
    unlocked_at = now - min(timedelta(seconds=seconds_since_unlock), UNLOCK_MAX_AGE)

    with transaction.atomic():
        locked_user = user.__class__.objects.select_for_update().get(pk=user.pk)

        _, softcore_created = UserUnlock.objects.get_or_create(
            user=locked_user,
            achievement=achievement,
            hardcore=False,
            defaults={"unlocked_at": unlocked_at},
        )
        if softcore_created:
            locked_user.softcore_points += achievement.points
            # A first unlock always creates the softcore row; a later hardcore one notifies nobody.
            notify_unlock(achievement, locked_user)

        hardcore_created = False
        if hardcore:
            _, hardcore_created = UserUnlock.objects.get_or_create(
                user=locked_user,
                achievement=achievement,
                hardcore=True,
                defaults={"unlocked_at": unlocked_at},
            )
            if hardcore_created:
                locked_user.hardcore_points += achievement.points

        locked_user.save(update_fields=["softcore_points", "hardcore_points"])
        PlayerGame.objects.update_or_create(
            user=locked_user,
            game=achievement.game,
            defaults={"last_played_at": now},
            create_defaults={"first_played_at": unlocked_at, "last_played_at": now},
        )
        remaining = _remaining_in_set(locked_user, achievement.game, hardcore)

    # A retry of an unlock already recorded was inspected when it first landed.
    if softcore_created or hardcore_created:
        inspect_unlock(locked_user, achievement, seconds_since_unlock, now)

    return {
        "Success": True,
        "Score": locked_user.hardcore_points,
        "SoftcoreScore": locked_user.softcore_points,
        "AchievementID": achievement_id,
        "AchievementsRemaining": remaining,
    }


def handle_ping(request):
    user, error = _authenticate(request)
    if error is not None:
        return error

    # rc_client sends `h` only alongside the game hash `x`, and omits `m` when it is empty.
    hardcore, error = _flag_param(request, "h")
    if error is not None:
        return error

    game = _game_by_id(request.POST.get("g", ""))
    if game is None:
        return _GAME_NOT_FOUND
    hash_game = _hash_game(request.POST.get("x", ""))
    if hash_game is None:
        session = game
    else:
        session = session_game(hash_game)

    rich_presence = request.POST.get("m", "")[:RICH_PRESENCE_MAX_LENGTH]
    _record_session_contact(user, session, hardcore, rich_presence=rich_presence)
    return {"Success": True}


TOP_ENTRIES_LIMIT = 10


def _rank_of(leaderboard, score):
    return rank_by_score(leaderboard_entries(leaderboard), leaderboard.lower_is_better, score)


def _ranked_entries(leaderboard, offset, count):
    return ranked_entries(
        leaderboard_entries(leaderboard), leaderboard.lower_is_better, offset, count
    )


def _top_entries(leaderboard):
    return [
        {"User": entry.user.username, "Score": entry.score, "Rank": rank}
        for _, rank, entry in _ranked_entries(leaderboard, 0, TOP_ENTRIES_LIMIT)
    ]


def handle_submitlbentry(request):
    user, error = _authenticate(request)
    if error is not None:
        return error

    try:
        leaderboard_id = int(request.POST.get("i", ""))
    except (ValueError, TypeError):
        return {"Success": False, "Error": "Unknown leaderboard"}

    try:
        score = int(request.POST.get("s", ""))
    except (ValueError, TypeError):
        return {"Success": False, "Error": "Invalid score"}
    if not MIN_INT32 <= score <= MAX_INT32:
        return {"Success": False, "Error": "Invalid score"}

    # `o` (seconds since the leaderboard completed) only enters the signature: an entry keeps
    # the time it reached the server.
    seconds_since_completion, error = _uint_param(request, "o", default=0)
    if error is not None:
        return error

    expected = leaderboard_validation_hash(
        leaderboard_id, request.POST.get("u", ""), score, seconds_since_completion
    )
    error = _signature_error(
        request,
        user,
        expected,
        leaderboard_id=leaderboard_id,
        score=score,
        seconds_since_completion=seconds_since_completion,
    )
    if error is not None:
        return error

    leaderboard = Leaderboard.objects.filter(pk=leaderboard_id).first()
    if leaderboard is None:
        return {"Success": False, "Error": "Unknown leaderboard"}

    with transaction.atomic():
        entry, created = LeaderboardEntry.objects.get_or_create(
            leaderboard=leaderboard, user=user, defaults={"score": score}
        )
        if not created:
            improved = score < entry.score if leaderboard.lower_is_better else score > entry.score
            if improved:
                entry.score = score
                entry.submitted_at = timezone.now()
                entry.save(update_fields=["score", "submitted_at"])

    return {
        "Success": True,
        "Response": {
            "Score": score,
            "BestScore": entry.score,
            "RankInfo": {
                "Rank": _rank_of(leaderboard, entry.score),
                "NumEntries": leaderboard_entries(leaderboard).count(),
            },
            "TopEntries": _top_entries(leaderboard),
        },
    }


LBINFO_DEFAULT_COUNT = 10
LBINFO_MAX_COUNT = 500
# The UTC "DB format" rcheevos' `rc_json_get_datetime` parses.
RCHEEVOS_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _rcheevos_datetime(moment):
    return moment.astimezone(UTC).strftime(RCHEEVOS_DATETIME_FORMAT)


def _position_of(leaderboard, entry):
    """1-based index of `entry` on the board: its rank plus the ties submitted before it."""
    earlier_ties = (
        leaderboard_entries(leaderboard)
        .filter(score=entry.score)
        .filter(
            Q(submitted_at__lt=entry.submitted_at)
            | Q(submitted_at=entry.submitted_at, id__lt=entry.id)
        )
        .count()
    )
    return _rank_of(leaderboard, entry.score) + earlier_ties


def _offset_around(position, count, total):
    """Entries to skip so the page of `count` centres on `position`, clamped to the board."""
    entries_above_position = count // 2
    offset = position - entries_above_position - 1
    if offset <= 0:
        return 0
    elif total - position + 1 < count:
        return max(0, total - count)
    else:
        return offset


def handle_lbinfo(request):
    leaderboard_id, error = _uint_param(request, "i")
    if error is not None:
        return error
    offset, error = _uint_param(request, "o", default=0)
    if error is not None:
        return error
    count, error = _uint_param(request, "c", default=LBINFO_DEFAULT_COUNT)
    if error is not None:
        return error
    count = min(count, LBINFO_MAX_COUNT)

    leaderboard = Leaderboard.objects.select_related("author").filter(pk=leaderboard_id).first()
    if leaderboard is None:
        return _not_found("leaderboard")

    total = leaderboard_entries(leaderboard).count()
    username = request.POST.get("u", "")
    # An unknown user, or one without an entry, gets the page `o` names, as on RA.
    user_entry = (
        leaderboard_entries(leaderboard).filter(user__username=username).first()
        if username
        else None
    )
    if user_entry is not None:
        offset = _offset_around(_position_of(leaderboard, user_entry), count, total)

    return {
        "Success": True,
        "LeaderboardData": {
            "LBID": leaderboard.pk,
            "GameID": leaderboard.game_id,
            # rcheevos reads LowerIsBetter here as an unsigned integer, not a boolean.
            "LowerIsBetter": int(leaderboard.lower_is_better),
            "LBTitle": leaderboard.title,
            "LBDesc": leaderboard.description,
            "LBFormat": leaderboard.format,
            "LBMem": leaderboard.mem_addr,
            # rcheevos accepts null, as RA sends for a leaderboard without an author.
            "LBAuthor": leaderboard.author.username if leaderboard.author else None,
            "LBCreated": _rcheevos_datetime(leaderboard.created_at),
            "LBUpdated": _rcheevos_datetime(leaderboard.updated_at),
            "TotalEntries": total,
            "Entries": [
                {
                    "User": entry.user.username,
                    "AvatarUrl": _user_avatar_url(request, entry.user.username),
                    "DateSubmitted": int(entry.submitted_at.timestamp()),
                    "Score": entry.score,
                    "Rank": rank,
                    "Index": index,
                }
                for index, rank, entry in _ranked_entries(leaderboard, offset, count)
            ],
        },
    }


def handle_systemgames(request):
    console_id, error = _uint_param(request, "s")
    if error is not None:
        return error
    console = Console.objects.filter(ra_id=console_id).first()
    if console is None:
        return _not_found("system")

    games = console.games.order_by("title", "id").prefetch_related("hashes")
    achievement_totals = {
        row["game"]: row
        for row in Achievement.objects.filter(
            game__console=console, status=Achievement.STATUS_OFFICIAL
        )
        .order_by()
        .values("game")
        .annotate(count=Count("id"), points=Sum("points"))
    }
    leaderboard_counts = dict(
        Leaderboard.objects.filter(game__console=console)
        .order_by()
        .values("game")
        .annotate(count=Count("id"))
        .values_list("game", "count")
    )
    no_achievements = {"count": 0, "points": 0}

    response = []
    for game in games:
        totals = achievement_totals.get(game.pk, no_achievements)
        response.append(
            {
                "ID": game.pk,
                "Title": game.title,
                "ImageIcon": game_icon_path(game),
                "ImageUrl": _game_icon_url(request, game),
                "NumAchievements": totals["count"],
                "NumLeaderboards": leaderboard_counts.get(game.pk, 0),
                "Points": totals["points"],
                "SupportedHashes": sorted(gh.md5.lower() for gh in game.hashes.all()),
            }
        )
    return {"Success": True, "Response": response}


GAMEINFOLIST_MAX_IDS = 100


def handle_gameinfolist(request):
    raw_param = request.POST.get("g", "")
    # Ids past the cap are ignored, as on RA.
    raw_ids = [raw for raw in raw_param.split(",") if raw][:GAMEINFOLIST_MAX_IDS]
    if raw_param == "":
        return _MISSING_PARAMETER
    elif not raw_ids:
        return _invalid_parameter("Invalid g: at least one game ID is required.")
    elif not all(_is_uint32(raw) for raw in raw_ids):
        return _invalid_parameter("Invalid g: expected comma-separated unsigned integers.")
    else:
        game_ids = {int(raw) for raw in raw_ids}

    games = Game.objects.filter(pk__in=game_ids).order_by("id")
    if not games:
        return _not_found("games")
    return {
        "Success": True,
        "Response": [
            {
                "ID": game.pk,
                "Title": game.title,
                "ImageIcon": game_icon_path(game),
                "ImageUrl": _game_icon_url(request, game),
            }
            for game in games
        ],
    }


def handle_hashlibrary(request):
    console_id, error = _uint_param(request, "c", default=0)
    if error is not None:
        return error

    # rcheevos omits `c`, asking for every console, when it is 0.
    if console_id == 0:
        hashes = GameHash.objects.all()
    elif Console.objects.filter(ra_id=console_id).exists():
        hashes = GameHash.objects.filter(game__console__ra_id=console_id)
    else:
        return _not_found("console")
    return {
        "Success": True,
        "MD5List": {md5.lower(): game_id for md5, game_id in hashes.values_list("md5", "game_id")},
    }


ACHIEVEMENTWONDATA_DEFAULT_COUNT = 10
ACHIEVEMENTWONDATA_MAX_COUNT = 500


def _achievement_winners(achievement):
    """One row per unlocker, latest first, dated by the hardcore unlock when there is one."""
    return (
        UserUnlock.objects.filter(achievement=achievement)
        .values("user_id", "user__username")
        .annotate(
            awarded_at=Coalesce(
                Min("unlocked_at", filter=Q(hardcore=True)),
                Min("unlocked_at", filter=Q(hardcore=False)),
            )
        )
        .order_by("-awarded_at", "user_id")
    )


def handle_achievementwondata(request):
    user, error = _authenticate(request)
    if error is not None:
        return error
    achievement_id, error = _uint_param(request, "a")
    if error is not None:
        return error
    friends_only, error = _flag_param(request, "f")
    if error is not None:
        return error
    offset, error = _uint_param(request, "o", default=0)
    if error is not None:
        return error
    count, error = _uint_param(request, "c", default=ACHIEVEMENTWONDATA_DEFAULT_COUNT)
    if error is not None:
        return error
    count = min(count, ACHIEVEMENTWONDATA_MAX_COUNT)

    achievement = Achievement.objects.select_related("game").filter(pk=achievement_id).first()
    if achievement is None:
        return _ACHIEVEMENT_NOT_FOUND

    winners = _achievement_winners(achievement)
    if friends_only:
        followed = Friendship.objects.filter(user=user, friend__is_active=True).values("friend")
        listed = winners.filter(user__in=followed)
    else:
        listed = winners
    page = listed[offset : offset + count]
    return {
        "Success": True,
        "AchievementID": achievement.pk,
        "Response": {
            "NumEarned": winners.count(),
            "TotalPlayers": _player_count(achievement.game),
            "GameID": achievement.game_id,
            "RecentWinner": [
                {
                    "User": winner["user__username"],
                    "DateAwarded": int(winner["awarded_at"].timestamp()),
                    "AvatarUrl": _user_avatar_url(request, winner["user__username"]),
                }
                for winner in page
            ],
        },
    }


# RAWeb's cap: only the most recently seen of the users followed.
FRIEND_LIST_MAX = 100
# What RAWeb answers as `LastSeen` when it knows no rich presence.
LAST_SEEN_UNKNOWN = "Unknown"


def _seen_at():
    """When a play record last saw its player: the latest ping, else the session start."""
    return Coalesce("last_ping_at", "last_played_at")


def _followed_users(user):
    """The active users `user` follows, most recently seen first, at most `FRIEND_LIST_MAX`."""
    last_seen_at = (
        PlayerGame.objects.filter(user=OuterRef("pk"))
        .annotate(seen_at=_seen_at())
        .order_by("-seen_at")
        .values("seen_at")[:1]
    )
    return (
        get_user_model()
        .objects.filter(followed_by__user=user, is_active=True)
        .annotate(last_seen_at=Subquery(last_seen_at))
        .order_by(F("last_seen_at").desc(nulls_last=True), "-hardcore_points", "username")
    )[:FRIEND_LIST_MAX]


def _latest_play_records(users):
    """Each user's most recently seen play record, by user id."""
    records = (
        PlayerGame.objects.filter(user__in=users)
        .annotate(seen_at=_seen_at())
        .select_related("game")
        .order_by("user_id", "-seen_at", "-id")
        .distinct("user_id")
    )
    return {record.user_id: record for record in records}


def _friend_entry(request, friend, record):
    """`rc_api_followed_user_t`: the last-seen fields come from the latest play record, null
    when the friend never played."""
    entry = {
        "Friend": friend.username,
        "AvatarUrl": _user_avatar_url(request, friend.username),
        "RAPoints": friend.hardcore_points,
    }
    if record is None:
        return {
            **entry,
            "LastSeen": LAST_SEEN_UNKNOWN,
            "LastSeenTime": None,
            "LastGameId": None,
            "LastGameTitle": None,
            "LastGameIconUrl": None,
        }
    else:
        return {
            **entry,
            "LastSeen": record.last_rich_presence or LAST_SEEN_UNKNOWN,
            "LastSeenTime": int(record.seen_at.timestamp()),
            "LastGameId": record.game_id,
            "LastGameTitle": record.game.title,
            "LastGameIconUrl": _game_icon_url(request, record.game),
        }


def handle_getfriendlist(request):
    user, error = _authenticate(request)
    if error is not None:
        return error
    friends = list(_followed_users(user))
    records = _latest_play_records(friends)
    return {
        "Success": True,
        "Friends": [_friend_entry(request, friend, records.get(friend.pk)) for friend in friends],
    }


def handle_latestclient(request):
    _, error = _uint_param(request, "e")
    if error is not None:
        return error
    # No client versions are published; `not_found` lets every emulator through.
    return _not_found("client")


HANDLERS = {
    "login2": handle_login2,
    "gameid": handle_gameid,
    "patch": handle_patch,
    "achievementsets": handle_achievementsets,
    "allprogress": handle_allprogress,
    "postactivity": handle_postactivity,
    "startsession": handle_startsession,
    "awardachievement": handle_awardachievement,
    "ping": handle_ping,
    "submitlbentry": handle_submitlbentry,
    "lbinfo": handle_lbinfo,
    "systemgames": handle_systemgames,
    "gameinfolist": handle_gameinfolist,
    "hashlibrary": handle_hashlibrary,
    "achievementwondata": handle_achievementwondata,
    "getfriendlist": handle_getfriendlist,
    "latestclient": handle_latestclient,
}
