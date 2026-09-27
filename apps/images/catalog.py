"""Which image each RA-compatible image name serves, and the versioned paths clients fetch."""

import hashlib
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse

from apps.achievements.models import PLACEHOLDER_BADGE_NAME, Badge
from apps.games.models import Game
from apps.images import rendering

GAME_IMAGE_NAME_DIGITS = 6
# rc_client_subset_t.badge_name (which rc_client_game_t.badge_name points to) is a char[16].
GAME_IMAGE_NAME_MAX_CHARS = 15
# rc_client's icon for an unknown game: always the placeholder, so no game is ever named it.
FALLBACK_GAME_IMAGE_NAME = "000001"
# Game image numbers start past the reserved fallback: game N is named N + this offset.
GAME_IMAGE_NUMBER_OFFSET = int(FALLBACK_GAME_IMAGE_NAME)
GAME_IMAGE_NAME_PATTERN = re.compile(rf"[0-9]{{1,{GAME_IMAGE_NAME_MAX_CHARS}}}")

# Part of every version: bump it when the drawing (placeholder, locked filter, identicon) changes.
IMAGE_RENDERING_REVISION = 1
VERSION_PARAM = "v"
VERSION_HEX_DIGITS = 12
RENDERED_IMAGE_CACHE_SECONDS = int(timedelta(days=1).total_seconds())
IDENTICON_SOURCE = "identicon"


def _source_digest(source):
    return hashlib.sha256(f"{IMAGE_RENDERING_REVISION}:{source}".encode()).hexdigest()


def _file_source(field_file):
    """What the image is drawn from: the stored file name, or "" for the placeholder.

    `field_file` is an empty `FieldFile` or `None` when nothing was uploaded.
    """
    # TRADEOFF: a new upload stored under the exact name of the file it replaces keeps its
    # version and cached rendering; Django renames colliding uploads, so only a file removed
    # by hand allows it. Hash the contents on upload if that ever matters.
    return field_file.name if field_file else ""


def _version(source):
    """Changes whenever the served image does, since DuckStation caches images by URL."""
    return _source_digest(source)[:VERSION_HEX_DIGITS]


def _versioned(path, source):
    return f"{path}?{VERSION_PARAM}={_version(source)}"


def _rendered_png(field_file, source, size, locked):
    """`(png, version)` of the upload, or of the placeholder when nothing was uploaded.

    `source` is what versions the image: it changes whenever the served image does.
    """

    def render():
        if field_file:
            image = rendering.uploaded_image(field_file, size)
        else:
            image = rendering.placeholder_image(size)
        return rendering.encode_png(rendering.locked_image(image) if locked else image)

    key = f"rendered-image:{size}:{int(locked)}:{_source_digest(source)}"
    return cache.get_or_set(key, render, RENDERED_IMAGE_CACHE_SECONDS), _version(source)


# --- Badges ---


def _badge_source(name):
    """A badge's image never changes under its name (new art is a new badge), so the name
    versions it; the placeholder is drawn from nothing."""
    if name == PLACEHOLDER_BADGE_NAME:
        return ""
    else:
        return f"badge:{name}"


def badge_path(name, locked=False):
    route = "badge-locked" if locked else "badge"
    return _versioned(reverse(route, args=[name]), _badge_source(name))


def badge_png(name, locked):
    """`(png, version)` of the badge named `name`, else `None`."""
    # TRADEOFF: every badge is served, drafts' included: the emulator fetches images without
    # credentials, and a draft's author must see its badge while testing it.
    if name == PLACEHOLDER_BADGE_NAME:
        return _rendered_png(None, _badge_source(name), rendering.BADGE_SIZE_PX, locked)
    badge = Badge.objects.named(name)
    if badge is None:
        return None
    else:
        return _rendered_png(badge.image, _badge_source(name), rendering.BADGE_SIZE_PX, locked)


# --- Game icons ---


def game_image_name(game):
    return f"{game.pk + GAME_IMAGE_NUMBER_OFFSET:0{GAME_IMAGE_NAME_DIGITS}d}"


def game_for_image_name(name):
    """The game whose icon `name` is, else `None`; only the canonical name matches."""
    if GAME_IMAGE_NAME_PATTERN.fullmatch(name) is None:
        return None
    game = Game.objects.filter(pk=int(name) - GAME_IMAGE_NUMBER_OFFSET).first()
    if game is not None and game_image_name(game) == name:
        return game
    else:
        return None


def game_icon_path(game):
    """The unversioned RA path, as `ImageIcon` carries it: rcheevos reads the name from it."""
    return reverse("game-icon", args=[game_image_name(game)])


def versioned_game_icon_path(game):
    return _versioned(game_icon_path(game), _file_source(game.icon))


def game_icon_png(name):
    """`(png, version)` of the game icon named `name`, else `None`."""
    if name == FALLBACK_GAME_IMAGE_NAME:
        return _rendered_png(None, "", rendering.GAME_ICON_SIZE_PX, locked=False)
    game = game_for_image_name(name)
    if game is None:
        return None
    else:
        return _rendered_png(
            game.icon, _file_source(game.icon), rendering.GAME_ICON_SIZE_PX, locked=False
        )


# --- Avatars ---


def avatar_path(username):
    return _versioned(reverse("user-pic", args=[username]), IDENTICON_SOURCE)


def avatar_png(username):
    """`(png, version)` of the user's identicon, else `None` for an unknown username."""
    if get_user_model().objects.filter(username=username).exists():
        return rendering.identicon_png(username), _version(IDENTICON_SOURCE)
    else:
        return None
