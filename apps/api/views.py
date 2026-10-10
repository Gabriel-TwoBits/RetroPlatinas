import logging
from http import HTTPStatus
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import Http404, HttpResponseNotAllowed, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.api.editor import EDITOR_HANDLERS, UPLOAD_HANDLERS
from apps.api.handlers import HANDLERS, _invalid_parameter
from apps.core import stats
from apps.games.models import Game, PlayerGame
from apps.images.catalog import badge_path

logger = logging.getLogger("apps.api")

# rc_client retries an unlock or leaderboard submission on 503 (and a few other statuses),
# never on Django's HTML 500, which would lose it.
_SERVER_ERROR = {
    "Success": False,
    "Error": "Temporary server error. Please try again.",
    "Status": HTTPStatus.SERVICE_UNAVAILABLE,
}
# Handler errors sent with their `Status` as the HTTP status, for rc_client to retry them.
RETRYABLE_STATUSES = frozenset({HTTPStatus.TOO_MANY_REQUESTS})

# rc_client builds every parameter from a C string, so a NUL never comes from it, and Postgres
# rejects NUL in text: a query or save carrying one would fail as a server error.
NUL = "\x00"


def _has_nul(params):
    return any(NUL in value for _, values in params.lists() for value in values)


def _unknown_action(action):
    return JsonResponse({"Success": False, "Error": f"Unknown action: {action}"})


@csrf_exempt
@require_POST
def dorequest(request):
    action = request.POST.get("r")
    if not action:
        return JsonResponse({"Success": False, "Error": "Missing 'r' parameter"})
    handler = HANDLERS.get(action) or EDITOR_HANDLERS.get(action)
    if handler is None:
        return _unknown_action(action)
    return _respond(request, action, handler)


@csrf_exempt
@require_POST
def doupload(request):
    """File uploads, named by `r` or, as RAWeb reads them, by the uploaded file's name."""
    upload = request.FILES.get("file")
    action = request.POST.get("r") or (Path(upload.name).stem if upload else "")
    handler = UPLOAD_HANDLERS.get(action)
    if handler is None:
        return _unknown_action(action)
    return _respond(request, action, handler)


def _respond(request, action, handler):
    if _has_nul(request.POST):
        return JsonResponse(_invalid_parameter("Parameters cannot contain NUL characters."))
    try:
        payload = handler(request)
    except Exception:
        logger.exception("api handler failed r=%s", action)
        return JsonResponse(_SERVER_ERROR, status=HTTPStatus.SERVICE_UNAVAILABLE)
    # rcheevos reads every error from the body; the HTTP status only decides whether to retry.
    if payload.get("Status") in RETRYABLE_STATUSES:
        return JsonResponse(payload, status=payload["Status"])
    else:
        return JsonResponse(payload)


def _unknown(resource, key):
    return JsonResponse({"Error": f"Unknown {resource} {key}."}, status=HTTPStatus.NOT_FOUND)


def debug_presence(request, username):
    """The user's live sessions (`PlayerGame.objects.playing_now`); a DEBUG-only test endpoint."""
    # DEBUG is checked before the method so the route answers 404 to anything without it.
    if not settings.DEBUG:
        raise Http404("Test endpoints exist only when DEBUG is on.")
    if request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
    user = get_user_model().objects.filter(username=username).first()
    if user is None:
        return _unknown("user", username)
    sessions = (
        PlayerGame.objects.playing_now().filter(user=user).select_related("game").order_by("game")
    )
    return JsonResponse(
        {
            "User": user.username,
            "Presence": [
                {
                    "GameID": session.game_id,
                    "Title": session.game.title,
                    "RichPresence": session.last_rich_presence,
                    "Hardcore": session.hardcore,
                    "LastPingAt": session.last_ping_at.isoformat(),
                }
                for session in sessions
            ],
        }
    )


RECENT_UNLOCKS_LIMIT = 20
LEADERBOARD_TOP_LIMIT = 100
# TRADEOFF: only the most recent players are listed; page through them if the list is ever shown
# in full.
GAME_PLAYERS_LIMIT = 100


def _by_mode(values):
    return {"Hardcore": values.hardcore, "Softcore": values.softcore}


@require_GET
def user_summary(request, username):
    user = get_user_model().objects.filter(username=username).first()
    if user is None:
        return _unknown("user", username)
    return JsonResponse(
        {
            "User": user.username,
            "Points": _by_mode(stats.ByMode(user.hardcore_points, user.softcore_points)),
            "Rank": _by_mode(stats.global_ranks(user)),
            "GamesPlayed": stats.games_played_count(user),
            "AchievementsUnlocked": _by_mode(stats.unlocked_achievement_counts(user)),
        }
    )


@require_GET
def user_recent_unlocks(request, username):
    user = get_user_model().objects.filter(username=username).first()
    if user is None:
        return _unknown("user", username)
    return JsonResponse(
        {
            "User": user.username,
            "Unlocks": [
                {
                    "AchievementID": unlock.achievement_id,
                    "Title": unlock.achievement.title,
                    "Description": unlock.achievement.description,
                    "Points": unlock.achievement.points,
                    "BadgeURL": request.build_absolute_uri(
                        badge_path(unlock.achievement.badge_name)
                    ),
                    "GameID": unlock.achievement.game_id,
                    "GameTitle": unlock.achievement.game.title,
                    "Hardcore": unlock.hardcore,
                    "UnlockedAt": unlock.unlocked_at.isoformat(),
                }
                for unlock in stats.recent_unlocks(user, RECENT_UNLOCKS_LIMIT)
            ],
        }
    )


@require_GET
def game_leaderboard(request, game_id, leaderboard_id):
    game = Game.objects.filter(pk=game_id).first()
    if game is None:
        return _unknown("game", game_id)
    # A leaderboard of another game answers as unknown under this one.
    leaderboard = game.leaderboards.filter(pk=leaderboard_id).first()
    if leaderboard is None:
        return _unknown("leaderboard", leaderboard_id)
    entries = stats.leaderboard_entries(leaderboard)
    return JsonResponse(
        {
            "GameID": game.pk,
            "LeaderboardID": leaderboard.pk,
            "Title": leaderboard.title,
            "Description": leaderboard.description,
            "Format": leaderboard.format,
            "LowerIsBetter": leaderboard.lower_is_better,
            "TotalEntries": entries.count(),
            "Entries": [
                {
                    "Rank": rank,
                    "User": entry.user.username,
                    "Score": entry.score,
                    "SubmittedAt": entry.submitted_at.isoformat(),
                }
                for _, rank, entry in stats.ranked_entries(
                    entries, leaderboard.lower_is_better, 0, LEADERBOARD_TOP_LIMIT
                )
            ],
        }
    )


@require_GET
def game_players(request, game_id):
    game = Game.objects.filter(pk=game_id).first()
    if game is None:
        return _unknown("game", game_id)
    return JsonResponse(
        {
            "GameID": game.pk,
            "Title": game.title,
            "AchievementsTotal": stats.official_achievement_count(game),
            "TotalPlayers": stats.game_players(game).count(),
            "Players": [
                {
                    "User": player.user.username,
                    "FirstPlayedAt": player.first_played_at.isoformat(),
                    "LastPlayedAt": player.last_played_at.isoformat(),
                    "PlaytimeSeconds": player.playtime_seconds,
                    "AchievementsUnlocked": _by_mode(
                        stats.ByMode(player.hardcore_unlocked, player.softcore_unlocked)
                    ),
                }
                for player in stats.game_players_with_progress(game, GAME_PLAYERS_LIMIT)
            ],
        }
    )
