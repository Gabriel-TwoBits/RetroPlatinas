from datetime import timedelta

from django.http import Http404, HttpResponse
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_safe

from apps.images import catalog

# A versioned URL never serves another image, so clients may keep it for good.
VERSIONED_MAX_AGE_SECONDS = int(timedelta(days=365).total_seconds())
# The bare RA path (and a stale version) serves whatever is current.
UNVERSIONED_MAX_AGE_SECONDS = int(timedelta(hours=1).total_seconds())


def _png_response(request, image):
    if image is None:
        raise Http404
    png, version = image
    response = HttpResponse(png, content_type="image/png")
    if request.GET.get(catalog.VERSION_PARAM) == version:
        patch_cache_control(
            response, public=True, max_age=VERSIONED_MAX_AGE_SECONDS, immutable=True
        )
    else:
        patch_cache_control(response, public=True, max_age=UNVERSIONED_MAX_AGE_SECONDS)
    return response


@require_safe
def badge(request, name):
    return _png_response(request, catalog.badge_png(name, locked=False))


@require_safe
def badge_locked(request, name):
    return _png_response(request, catalog.badge_png(name, locked=True))


@require_safe
def game_icon(request, name):
    return _png_response(request, catalog.game_icon_png(name))


@require_safe
def user_pic(request, username):
    return _png_response(request, catalog.avatar_png(username))
