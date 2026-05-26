import secrets
from datetime import timedelta

from django.contrib.auth import authenticate
from django.utils import timezone

_NOT_IMPLEMENTED = {"Success": False, "Error": "not implemented"}
_INVALID_CREDENTIALS = {"Success": False, "Error": "Credentials invalid.", "Status": 401}


def handle_login2(request):
    username = request.POST.get("u")
    password = request.POST.get("p")
    if not username or not password:
        return _INVALID_CREDENTIALS
    user = authenticate(username=username, password=password)
    if user is None:
        return _INVALID_CREDENTIALS
    token = secrets.token_hex(32)
    user.api_token = token
    user.api_token_expires_at = timezone.now() + timedelta(days=14)
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
    return _NOT_IMPLEMENTED


def handle_patch(request):
    return _NOT_IMPLEMENTED


def handle_postactivity(request):
    return _NOT_IMPLEMENTED


def handle_startsession(request):
    return _NOT_IMPLEMENTED


def handle_awardachievement(request):
    return _NOT_IMPLEMENTED


def handle_ping(request):
    return _NOT_IMPLEMENTED


def handle_submitlbentry(request):
    return _NOT_IMPLEMENTED


HANDLERS = {
    "login2": handle_login2,
    "gameid": handle_gameid,
    "patch": handle_patch,
    "postactivity": handle_postactivity,
    "startsession": handle_startsession,
    "awardachievement": handle_awardachievement,
    "ping": handle_ping,
    "submitlbentry": handle_submitlbentry,
}
