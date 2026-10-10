from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.utils.translation import gettext
from django.views.decorators.http import require_safe

from .feed import (
    FEED_UNLOCKS_SHOWN,
    FILTER_ALL,
    FILTER_FRIENDS,
    FILTERS,
    POLL_SECONDS,
    VALID_FILTERS,
    feed_rows,
)
from .home import home_context
from .htmx import login_redirect


def home(request):
    return render(request, "home.html", home_context())


def _render_feed(request, template):
    """The feed or its list fragment under the `filter` parameter; the friends feed needs a
    session."""
    feed_filter = request.GET.get("filter", FILTER_ALL)
    if feed_filter not in VALID_FILTERS:
        return HttpResponseBadRequest(gettext("Unknown feed filter"))
    elif feed_filter == FILTER_FRIENDS and not request.user.is_authenticated:
        return login_redirect(request)
    else:
        context = {
            "rows": feed_rows(feed_filter, request.user),
            "feed_filter": feed_filter,
            "filters": FILTERS,
            "shown": FEED_UNLOCKS_SHOWN,
            "poll_seconds": POLL_SECONDS,
        }
        return render(request, template, context)


@require_safe
def feed(request):
    return _render_feed(request, "feed/feed.html")


@require_safe
def feed_list(request):
    return _render_feed(request, "feed/partials/feed-list.html")


def getting_started(request):
    # The address DuckStation needs as its [Cheevos] Host: this site's origin, no trailing slash.
    server_url = request.build_absolute_uri("/").rstrip("/")
    return render(request, "docs/getting-started.html", {"server_url": server_url})
