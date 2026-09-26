import logging
import secrets
from datetime import timedelta
from http import HTTPStatus

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import API_TOKEN_BYTES
from apps.achievements.models import Achievement, UserUnlock
from apps.api.auth import is_expired_token, user_from_token
from apps.games.models import Game, GameHash
from apps.leaderboards.models import Leaderboard, LeaderboardEntry

logger = logging.getLogger("apps.api")

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
_GAME_NOT_FOUND = {
    "Success": False,
    "Error": "Unknown game.",
    "Status": HTTPStatus.NOT_FOUND,
    "Code": "not_found",
}
_ACHIEVEMENT_NOT_FOUND = {
    "Success": False,
    "Error": "Unknown achievement.",
    "Status": HTTPStatus.NOT_FOUND,
    "Code": "not_found",
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
    # TRADEOFF: a player is a user with any unlock in the game, so players who never
    # unlocked anything are not counted; count PlayerGame rows once sessions are recorded.
    return UserUnlock.objects.filter(achievement__game=game).values("user").distinct().count()


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
        "Flags": _achievement_flags(a),
        "Type": a.type,
        "Rarity": _rarity(a.unlockers, players),
        "RarityHardcore": _rarity(a.hardcore_unlockers, players),
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

    try:
        game_id = int(request.POST.get("g", ""))
    except (ValueError, TypeError):
        return {"Success": False, "Error": "Unknown game"}

    game = Game.objects.select_related("console").filter(pk=game_id).first()
    if game is None:
        return {"Success": False, "Error": "Unknown game"}

    achievements = _served_achievements(user, game)
    players = _player_count(game)
    image_icon = game.icon.url if game.icon else DEFAULT_GAME_ICON_PATH
    return {
        "Success": True,
        "PatchData": {
            "ID": game.pk,
            "Title": game.title,
            "ConsoleID": game.console.ra_id,
            "ImageIcon": image_icon,
            "RichPresencePatch": game.rich_presence_patch,
            "Achievements": [_serialize_achievement(a, players) for a in achievements],
            "Leaderboards": [_serialize_leaderboard(lb) for lb in game.leaderboards.all()],
        },
    }


def handle_achievementsets(request):
    user, error = _authenticate(request)
    if error is not None:
        return error

    md5 = request.POST.get("m", "").lower()
    game_id_param = request.POST.get("g", "")
    if md5:
        game = Game.objects.select_related("console").filter(hashes__md5=md5).first()
    elif game_id_param:
        try:
            game = Game.objects.select_related("console").filter(pk=int(game_id_param)).first()
        except (ValueError, TypeError):
            game = None
    else:
        game = None

    if game is None:
        logger.info("achievementsets unknown game hash=%s g=%s", md5, game_id_param)
        return _GAME_NOT_FOUND

    achievements = _served_achievements(user, game)
    players = _player_count(game)
    icon_path = game.icon.url if game.icon else DEFAULT_GAME_ICON_PATH
    icon_url = request.build_absolute_uri(icon_path)
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

    try:
        game_id = int(request.POST.get("g", ""))
    except (ValueError, TypeError):
        return {"Success": False, "Error": "Unknown game"}

    unlocks = UserUnlock.objects.filter(user=user, achievement__game_id=game_id).values(
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
    better = "score__lt" if leaderboard.lower_is_better else "score__gt"
    return leaderboard.entries.filter(**{better: score}).count() + 1


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

    order = "score" if leaderboard.lower_is_better else "-score"
    ranked = leaderboard.entries.select_related("user").order_by(order, "submitted_at")
    top_entries = [
        {"User": e.user.username, "Score": e.score, "Rank": rank}
        for rank, e in enumerate(ranked[:TOP_ENTRIES_LIMIT], start=1)
    ]

    return {
        "Success": True,
        "Response": {
            "Score": score,
            "BestScore": entry.score,
            "RankInfo": {
                "Rank": _rank_of(leaderboard, entry.score),
                "NumEntries": leaderboard.entries.count(),
            },
            "TopEntries": top_entries,
        },
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
}
