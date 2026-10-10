"""Login redirects that work for htmx requests as well as plain ones."""

from functools import wraps
from urllib.parse import urlsplit

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponse


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _current_page(request):
    """The path and query of the page that sent an htmx request, `""` when unknown."""
    url = urlsplit(request.headers.get("HX-Current-URL", ""))
    if url.query:
        return f"{url.path}?{url.query}"
    else:
        return url.path


def login_redirect(request, fragment=""):
    """Sends the visitor to log in and back. For htmx, `HX-Redirect` returns to the page (plus
    `fragment`): the XHR would follow a 302 and swap the whole login page into the target."""
    page = _current_page(request)
    if is_htmx(request) and page:
        response = HttpResponse()
        response["HX-Redirect"] = redirect_to_login(f"{page}{fragment}")["Location"]
        return response
    else:
        return redirect_to_login(request.get_full_path())


def login_required(fragment=""):
    """`login_required` answering an anonymous request with `login_redirect`."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.user.is_authenticated:
                return view(request, *args, **kwargs)
            else:
                return login_redirect(request, fragment)

        return wrapper

    return decorator
