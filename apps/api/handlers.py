import secrets
from datetime import timedelta

from django.contrib.auth import authenticate
from django.utils import timezone

from apps.achievements.models import Achievement
from apps.api.auth import user_from_token
from apps.games.models import Game, GameHash

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
    md5 = request.POST.get("m", "").lower()
    if not md5:
        return {"Success": True, "GameID": 0}
    game_id = GameHash.objects.filter(md5=md5).values_list("game_id", flat=True).first()
    return {"Success": True, "GameID": game_id if game_id is not None else 0}


def _serialize_achievement(a):
    flags = 3 if a.status == Achievement.STATUS_VERIFIED else 5
    return {
        "ID": a.id,
        "MemAddr": a.mem_addr,
        "Title": a.title,
        "Description": a.description,
        "Points": a.points,
        "Author": a.author.username,
        "Modified": int(a.updated_at.timestamp()),
        "Created": int(a.created_at.timestamp()),
        "BadgeName": f"{a.id:05d}",
        "Flags": flags,
    }


def handle_patch(request):
    user = user_from_token(request.POST.get("t", ""))
    if user is None:
        return _INVALID_CREDENTIALS

    try:
        game_id = int(request.POST.get("g", ""))
    except (ValueError, TypeError):
        return {"Success": False, "Error": "Unknown game"}

    game = Game.objects.select_related("console").filter(pk=game_id).first()
    if game is None:
        return {"Success": False, "Error": "Unknown game"}

    achievements = (
        game.achievements
        .filter(status__in=[Achievement.STATUS_COMMUNITY, Achievement.STATUS_VERIFIED])
        .select_related("author")
        .order_by("id")
    )
    image_icon = game.icon.url if game.icon else "/Images/000000.png"
    return {
        "Success": True,
        "PatchData": {
            "ID": game.pk,
            "Title": game.title,
            "ConsoleID": game.console.ra_id,
            "ImageIcon": image_icon,
            "RichPresencePatch": game.rich_presence_patch,
            "Achievements": [_serialize_achievement(a) for a in achievements],
            "Leaderboards": [],
        },
    }


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
