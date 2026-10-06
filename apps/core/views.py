from django.shortcuts import render
from django.views.decorators.http import require_safe

from .feed import FEED_UNLOCKS_SHOWN, POLL_SECONDS, feed_rows
from .home import home_context


def home(request):
    return render(request, "home.html", home_context())


@require_safe
def feed(request):
    context = {
        "rows": feed_rows(),
        "shown": FEED_UNLOCKS_SHOWN,
        "poll_seconds": POLL_SECONDS,
    }
    return render(request, "feed/feed.html", context)


@require_safe
def feed_list(request):
    return render(request, "feed/partials/feed-list.html", {"rows": feed_rows()})


def getting_started(request):
    # The address DuckStation needs as its [Cheevos] Host: this site's origin, no trailing slash.
    server_url = request.build_absolute_uri("/").rstrip("/")
    return render(request, "docs/getting-started.html", {"server_url": server_url})
