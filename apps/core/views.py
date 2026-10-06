from django.shortcuts import render

from .fake_home import fake_home_context


def home(request):
    return render(request, "home.html", fake_home_context())


def getting_started(request):
    # The address DuckStation needs as its [Cheevos] Host: this site's origin, no trailing slash.
    server_url = request.build_absolute_uri("/").rstrip("/")
    return render(request, "docs/getting-started.html", {"server_url": server_url})
