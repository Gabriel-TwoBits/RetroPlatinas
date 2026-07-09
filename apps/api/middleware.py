import logging

logger = logging.getLogger("apps.api")


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != "/dorequest.php":
            return self.get_response(request)

        action = request.POST.get("r", "")
        username = request.POST.get("u", "")
        ip = request.META.get("REMOTE_ADDR", "")

        response = self.get_response(request)

        logger.info(
            "api request r=%s u=%s ip=%s status=%s",
            action,
            username,
            ip,
            response.status_code,
        )
        return response
