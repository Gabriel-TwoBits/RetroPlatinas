import logging
from http import HTTPStatus

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.api.handlers import HANDLERS

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
