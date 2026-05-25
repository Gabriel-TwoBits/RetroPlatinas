_NOT_IMPLEMENTED = {"Success": False, "Error": "not implemented"}


def handle_login2(request):
    return _NOT_IMPLEMENTED


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
