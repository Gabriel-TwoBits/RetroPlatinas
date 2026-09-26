import logging
import re
import secrets
from datetime import timedelta
from http import HTTPStatus
from urllib.parse import quote

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.accounts.models import API_TOKEN_BYTES
from apps.achievements.models import Achievement, UserUnlock
from apps.api.auth import is_expired_token, user_from_token
from apps.games.models import Console, Game, GameHash
from apps.leaderboards.models import Leaderboard, LeaderboardEntry

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
_ACHIEVEMENT_UNPUBLISHED = {
    "Success": False,
    "Error": "Unpublished achievements cannot be unlocked.",
    "Status": HTTPStatus.CONFLICT,
    "Code": "invalid_state",
}

# rcheevos RC_ACHIEVEMENT_CATEGORY_CORE / RC_ACHIEVEMENT_CATEGORY_UNOFFICIAL.
ACHIEVEMENT_FLAGS_CORE = 3
ACHIEVEMENT_FLAGS_UNOFFICIAL = 5

PRESENCE_TTL_SECONDS = 300
DEFAULT_GAME_ICON_PATH = "/Images/000001.png"
API_TOKEN_LIFETIME = timedelta(days=14)
BADGE_NAME_DIGITS = 5
PERCENT = 100
# rcheevos' JSON parser reads plain decimals only: `1e-05` would not parse.
RARITY_DECIMAL_PLACES = 2


# rcheevos sends every id, offset and count as a uint32.
MAX_UINT32 = 0xFFFFFFFF
# Bounds the digits before `int()`, which rejects strings past Python's digit limit.
UINT32_PATTERN = re.compile(rf"[0-9]{{1,{len(str(MAX_UINT32))}}}")


def _invalid_parameter(message):
    return {
        "Success": False,
        "Error": message,
        "Status": HTTPStatus.UNPROCESSABLE_ENTITY,
        "Code": "invalid_parameter",
    }


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


def _user_avatar_url(request, username):
    """Absolute URL of the RA-compatible avatar path, so clients never fall back to RA's host."""
    return request.build_absolute_uri(f"/UserPic/{quote(username)}.png")


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


def _game_from_request(request):
    """The game named by the `m` hash, else by the `g` id; `None` when neither matches."""
    md5 = request.POST.get("m", "").lower()
    game_id_param = request.POST.get("g", "")
    if md5:
        return Game.objects.select_related("console").filter(hashes__md5=md5).first()
    elif game_id_param:
        return _game_by_id(game_id_param)
    else:
        return None


def _achievements_visible_to(user):
    return Achievement.objects.filter(
        Q(status__in=Achievement.PUBLISHED_STATUSES)
        | Q(status=Achievement.STATUS_DRAFT, author=user)
    )


def _served_achievements(user, game):
    return (
        _achievements_visible_to(user)
        .filter(game=game)
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
    # TRADEOFF: a player is a user with any published unlock in the game, so players who
    # never unlocked anything are not counted; count PlayerGame rows once sessions are recorded.
    return (
        UserUnlock.objects.filter(
            achievement__game=game, achievement__status__in=Achievement.PUBLISHED_STATUSES
        )
        .values("user")
        .distinct()
        .count()
    )


def _rarity(unlockers, players):
    """Percentage of the game's players who unlocked it, as rcheevos' `Rarity` expects."""
    if players == 0:
        return 0.0
    else:
        return round(unlockers * PERCENT / players, RARITY_DECIMAL_PLACES)


def _achievement_flags(achievement):
    if achievement.status in Achievement.PUBLISHED_STATUSES:
        return ACHIEVEMENT_FLAGS_CORE
    elif achievement.status == Achievement.STATUS_DRAFT:
        return ACHIEVEMENT_FLAGS_UNOFFICIAL
    else:
        raise ValueError(f"Achievement {achievement.pk} has unknown status {achievement.status!r}")


def _serialize_achievement(a, players):
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
        "BadgeName": f"{a.id:0{BADGE_NAME_DIGITS}d}",
        "Flags": flags,
        "Type": a.type,
        "Rarity": rarity,
        "RarityHardcore": rarity_hardcore,
    }


def _game_icon_path(game):
    """The icon's path; clients read the badge name from its filename."""
    if game.icon:
        return game.icon.url
    else:
        return DEFAULT_GAME_ICON_PATH


def _game_icon_url(request, game):
    return request.build_absolute_uri(_game_icon_path(game))


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

    achievements = _served_achievements(user, game)
    players = _player_count(game)
    return {
        "Success": True,
        "PatchData": {
            "ID": game.pk,
            "Title": game.title,
            "ConsoleID": game.console.ra_id,
            "ImageIcon": _game_icon_path(game),
            "RichPresencePatch": game.rich_presence_patch,
            "Achievements": [_serialize_achievement(a, players) for a in achievements],
            "Leaderboards": [_serialize_leaderboard(lb) for lb in game.leaderboards.all()],
        },
    }


def handle_achievementsets(request):
    user, error = _authenticate(request)
    if error is not None:
        return error

    game = _game_from_request(request)
    if game is None:
        logger.info(
            "achievementsets unknown game hash=%s g=%s",
            request.POST.get("m", ""),
            request.POST.get("g", ""),
        )
        return _GAME_NOT_FOUND

    achievements = _served_achievements(user, game)
    players = _player_count(game)
    icon_url = _game_icon_url(request, game)
    return {
        "Success": True,
        "GameId": game.pk,
        "Title": game.title,
        "ConsoleId": game.console.ra_id,
        "ImageIconUrl": icon_url,
        "RichPresenceGameId": game.pk,
        "RichPresencePatch": game.rich_presence_patch,
        # TRADEOFF: one core set per game, so game.pk doubles as the set id; a set model
        # takes over when subsets (bonus/specialty) are supported.
        "Sets": [
            {
                "AchievementSetId": game.pk,
                "GameId": game.pk,
                "Title": game.title,
                "Type": "core",
                "ImageIconUrl": icon_url,
                "Achievements": [_serialize_achievement(a, players) for a in achievements],
                "Leaderboards": [_serialize_leaderboard(lb) for lb in game.leaderboards.all()],
            }
        ],
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


def handle_startsession(request):
    user, error = _authenticate(request)
    if error is not None:
        return error

    game = _game_by_id(request.POST.get("g", ""))
    if game is None:
        return _GAME_NOT_FOUND

    unlocks = UserUnlock.objects.filter(user=user, achievement__game=game).values(
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
    total = game.achievements.filter(status__in=Achievement.PUBLISHED_STATUSES).count()
    unlocked = UserUnlock.objects.filter(
        user=user,
        hardcore=hardcore,
        achievement__game=game,
        achievement__status__in=Achievement.PUBLISHED_STATUSES,
    ).count()
    return max(total - unlocked, 0)


def handle_awardachievement(request):
    user, error = _authenticate(request)
    if error is not None:
        return error

    try:
        achievement_id = int(request.POST.get("a", ""))
    except (ValueError, TypeError):
        return _ACHIEVEMENT_NOT_FOUND

    # Another user's draft answers as unknown, so drafts stay invisible to everyone but the author.
    achievement = (
        _achievements_visible_to(user).select_related("game").filter(pk=achievement_id).first()
    )
    if achievement is None:
        return _ACHIEVEMENT_NOT_FOUND
    if achievement.status not in Achievement.PUBLISHED_STATUSES:
        return _ACHIEVEMENT_UNPUBLISHED

    hardcore = request.POST.get("h", "0") == "1"

    with transaction.atomic():
        locked_user = user.__class__.objects.select_for_update().get(pk=user.pk)

        _, softcore_created = UserUnlock.objects.get_or_create(
            user=locked_user, achievement=achievement, hardcore=False
        )
        if softcore_created:
            locked_user.softcore_points += achievement.points

        if hardcore:
            _, hardcore_created = UserUnlock.objects.get_or_create(
                user=locked_user, achievement=achievement, hardcore=True
            )
            if hardcore_created:
                locked_user.hardcore_points += achievement.points

        locked_user.save(update_fields=["softcore_points", "hardcore_points"])
        remaining = _remaining_in_set(locked_user, achievement.game, hardcore)

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

    try:
        game_id = int(request.POST.get("g", ""))
    except (ValueError, TypeError):
        return {"Success": False, "Error": "Unknown game"}

    rich_presence = request.POST.get("m", "")
    cache.set(f"presence:{user.id}:{game_id}", rich_presence, PRESENCE_TTL_SECONDS)
    return {"Success": True}


TOP_ENTRIES_LIMIT = 10


def _rank_of(leaderboard, score):
    """Competition rank ("1224"): one more than the number of strictly better scores."""
    better = "score__lt" if leaderboard.lower_is_better else "score__gt"
    return leaderboard.entries.filter(**{better: score}).count() + 1


def _ranked_entries(leaderboard, offset, count):
    """`(index, rank, entry)` for `count` entries after the first `offset`, best first.

    `index` is the 1-based position on the board; tied scores share the competition rank
    `_rank_of` gives them.
    """
    order = "score" if leaderboard.lower_is_better else "-score"
    board = leaderboard.entries.select_related("user").order_by(order, "submitted_at", "id")
    ranked = []
    previous_score = None
    previous_rank = None
    for index, entry in enumerate(board[offset : offset + count], start=offset + 1):
        if previous_rank is None:
            rank = _rank_of(leaderboard, entry.score)
        elif entry.score == previous_score:
            rank = previous_rank
        else:
            rank = index
        ranked.append((index, rank, entry))
        previous_score = entry.score
        previous_rank = rank
    return ranked


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

    leaderboard = Leaderboard.objects.filter(pk=leaderboard_id).first()
    if leaderboard is None:
        return {"Success": False, "Error": "Unknown leaderboard"}

    try:
        score = int(request.POST.get("s", ""))
    except (ValueError, TypeError):
        return {"Success": False, "Error": "Invalid score"}

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
                "NumEntries": leaderboard.entries.count(),
            },
            "TopEntries": _top_entries(leaderboard),
        },
    }


LBINFO_DEFAULT_COUNT = 10
LBINFO_MAX_COUNT = 500
# Leaderboards record no creation or update time, yet rcheevos requires both as datetime
# strings; rc_client never reads them.
LEADERBOARD_UNKNOWN_DATETIME = "1970-01-01 00:00:00"


def _position_of(leaderboard, entry):
    """1-based index of `entry` on the board: its rank plus the ties submitted before it."""
    earlier_ties = (
        leaderboard.entries.filter(score=entry.score)
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

    leaderboard = Leaderboard.objects.filter(pk=leaderboard_id).first()
    if leaderboard is None:
        return _not_found("leaderboard")

    total = leaderboard.entries.count()
    username = request.POST.get("u", "")
    # An unknown user, or one without an entry, gets the page `o` names, as on RA.
    user_entry = leaderboard.entries.filter(user__username=username).first() if username else None
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
            # No leaderboard author is recorded; rcheevos accepts null, as RA sends for none.
            "LBAuthor": None,
            "LBCreated": LEADERBOARD_UNKNOWN_DATETIME,
            "LBUpdated": LEADERBOARD_UNKNOWN_DATETIME,
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
            game__console=console, status__in=Achievement.PUBLISHED_STATUSES
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
                "ImageIcon": _game_icon_path(game),
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
                "ImageIcon": _game_icon_path(game),
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
}
