import logging
from http import HTTPStatus

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import Http404, HttpResponseNotAllowed, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.api.handlers import HANDLERS, _invalid_parameter
from apps.games.models import PlayerGame

logger = logging.getLogger("apps.api")

# rc_client retries an unlock or leaderboard submission on 503 (and a few other statuses),
# never on Django's HTML 500, which would lose it.
_SERVER_ERROR = {
    "Success": False,
    "Error": "Temporary server error. Please try again.",
    "Status": HTTPStatus.SERVICE_UNAVAILABLE,
}

# rc_client builds every parameter from a C string, so a NUL never comes from it, and Postgres
# rejects NUL in text: a query or save carrying one would fail as a server error.
NUL = "\x00"


def _has_nul(params):
    return any(NUL in value for _, values in params.lists() for value in values)


@csrf_exempt
@require_POST
def dorequest(request):
    action = request.POST.get("r")
    if not action:
        return JsonResponse({"Success": False, "Error": "Missing 'r' parameter"})
    handler = HANDLERS.get(action)
    if handler is None:
        return JsonResponse({"Success": False, "Error": f"Unknown action: {action}"})
    elif _has_nul(request.POST):
        return JsonResponse(_invalid_parameter("Parameters cannot contain NUL characters."))
    try:
        return JsonResponse(handler(request))
    except Exception:
        logger.exception("api handler failed r=%s", action)
        return JsonResponse(_SERVER_ERROR, status=HTTPStatus.SERVICE_UNAVAILABLE)


def debug_presence(request, username):
    """The user's live sessions (`PlayerGame.objects.playing_now`); a DEBUG-only test endpoint."""
    # DEBUG is checked before the method so the route answers 404 to anything without it.
    if not settings.DEBUG:
        raise Http404("Test endpoints exist only when DEBUG is on.")
    elif request.method != "GET":
        return HttpResponseNotAllowed(["GET"])
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
