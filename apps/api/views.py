from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.api.handlers import HANDLERS


@csrf_exempt
@require_POST
def dorequest(request):
    action = request.POST.get("r")
    if not action:
        return JsonResponse({"Success": False, "Error": "Missing 'r' parameter"})
    handler = HANDLERS.get(action)
    if handler is None:
        return JsonResponse({"Success": False, "Error": f"Unknown action: {action}"})
    return JsonResponse(handler(request))
