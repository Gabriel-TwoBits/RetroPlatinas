import logging
from http import HTTPStatus

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import Http404, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.api.handlers import HANDLERS
from apps.games.models import PlayerGame

logger = logging.getLogger("apps.api")

# rc_client retries an unlock or leaderboard submission on 503 (and a few other statuses),
# never on Django's HTML 500, which would lose it.
_SERVER_ERROR = {
    "Success": False,
    "Error": "Temporary server error. Please try again.",
    "Status": HTTPStatus.SERVICE_UNAVAILABLE,
}


@csrf_exempt
@require_POST
def dorequest(request):
    action = request.POST.get("r")
    if not action:
        return JsonResponse({"Success": False, "Error": "Missing 'r' parameter"})
    handler = HANDLERS.get(action)
    if handler is None:
        return JsonResponse({"Success": False, "Error": f"Unknown action: {action}"})
    try:
        return JsonResponse(handler(request))
    except Exception:
        logger.exception("api handler failed r=%s", action)
        return JsonResponse(_SERVER_ERROR, status=HTTPStatus.SERVICE_UNAVAILABLE)


@require_GET
def debug_presence(request, username):
    """The user's live sessions (`PlayerGame.objects.playing_now`); a DEBUG-only test endpoint."""
    if not settings.DEBUG:
        raise Http404("Test endpoints exist only when DEBUG is on.")
    user = get_user_model().objects.filter(username=username).first()
    if user is None:
        return JsonResponse({"Error": f"Unknown user {username}."}, status=HTTPStatus.NOT_FOUND)
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
