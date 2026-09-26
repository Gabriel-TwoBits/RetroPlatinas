import io
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.achievements.models import Achievement
from apps.games.models import Console, Game
from apps.images.catalog import (
    FALLBACK_GAME_IMAGE_NAME,
    VERSION_PARAM,
    avatar_path,
    badge_name,
    badge_path,
    game_image_name,
    versioned_game_icon_path,
)
from apps.images.rendering import (
    AVATAR_SIZE_PX,
    BADGE_SIZE_PX,
    GAME_ICON_SIZE_PX,
    placeholder_image,
)
from apps.images.views import UNVERSIONED_MAX_AGE_SECONDS, VERSIONED_MAX_AGE_SECONDS

User = get_user_model()

RED = (220, 30, 30, 255)
BLUE = (30, 30, 220, 255)
UPLOAD_SIZE_PX = 128


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    cache.clear()


def _png_upload(name, color, size=UPLOAD_SIZE_PX):
    buffer = io.BytesIO()
    Image.new("RGBA", (size, size), color).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def _image(response):
    assert response.status_code == HTTPStatus.OK
    assert response["Content-Type"] == "image/png"
    return Image.open(io.BytesIO(response.content)).convert("RGBA")


@pytest.fixture
def game(db):
    console = Console.objects.create(ra_id=12, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


@pytest.fixture
def achievement(game):
    author = User.objects.create_user(username="author", password="pw")
    return Achievement.objects.create(
        game=game,
        author=author,
        title="Boulders",
        description="d",
        points=5,
        mem_addr="0xH0001=1",
        status=Achievement.STATUS_COMMUNITY,
    )


# --- Badges ---


@pytest.mark.django_db
def test_badge_serves_the_uploaded_badge_as_a_64px_png(client, achievement):
    achievement.badge = _png_upload("boulders.png", RED)
    achievement.save()

    image = _image(client.get(f"/Badge/{badge_name(achievement)}.png"))

    assert image.size == (BADGE_SIZE_PX, BADGE_SIZE_PX)
    assert image.getpixel((0, 0)) == RED


@pytest.mark.django_db
def test_badge_serves_the_placeholder_without_an_upload(client, achievement):
    image = _image(client.get(f"/Badge/{badge_name(achievement)}.png"))

    assert image.tobytes() == placeholder_image(BADGE_SIZE_PX).tobytes()


@pytest.mark.django_db
def test_locked_badge_is_a_grayscale_variant(client, achievement):
    achievement.badge = _png_upload("boulders.png", RED)
    achievement.save()

    image = _image(client.get(f"/Badge/{badge_name(achievement)}_lock.png"))

    assert image.size == (BADGE_SIZE_PX, BADGE_SIZE_PX)
    assert all(r == g == b for r, g, b, _ in image.get_flattened_data())
    assert image.getpixel((0, 0)) != RED


@pytest.mark.django_db
def test_locked_placeholder_is_grayscale(client, achievement):
    image = _image(client.get(f"/Badge/{badge_name(achievement)}_lock.png"))

    assert all(r == g == b for r, g, b, _ in image.get_flattened_data())


@pytest.mark.django_db
def test_locked_badge_follows_a_new_upload(client, achievement):
    achievement.badge = _png_upload("boulders.png", RED)
    achievement.save()
    red_locked = client.get(f"/Badge/{badge_name(achievement)}_lock.png").content

    achievement.badge = _png_upload("boulders.png", BLUE)
    achievement.save()
    blue_locked = client.get(f"/Badge/{badge_name(achievement)}_lock.png").content

    assert blue_locked != red_locked


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/Badge/99999.png", "/Badge/99999_lock.png", "/Badge/1.png"])
def test_badge_unknown_or_non_canonical_name_is_not_found(client, achievement, path):
    assert client.get(path).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_badge_rejects_writes(client, achievement):
    response = client.post(f"/Badge/{badge_name(achievement)}.png")
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


# --- Versioning and caching ---


@pytest.mark.django_db
def test_badge_path_changes_when_a_badge_is_uploaded(achievement):
    placeholder_path = badge_path(achievement)
    locked_placeholder_path = badge_path(achievement, locked=True)

    achievement.badge = _png_upload("boulders.png", RED)
    achievement.save()

    assert badge_path(achievement) != placeholder_path
    assert badge_path(achievement, locked=True) != locked_placeholder_path
    assert badge_path(achievement).startswith(f"/Badge/{badge_name(achievement)}.png?")
    assert badge_path(achievement, locked=True).startswith(
        f"/Badge/{badge_name(achievement)}_lock.png?"
    )


@pytest.mark.django_db
def test_badge_path_changes_when_the_badge_is_replaced(achievement):
    achievement.badge = _png_upload("boulders.png", RED)
    achievement.save()
    first = badge_path(achievement)

    achievement.badge = _png_upload("boulders.png", BLUE)
    achievement.save()

    assert badge_path(achievement) != first


@pytest.mark.django_db
def test_current_version_is_cached_for_good(client, achievement):
    response = client.get(badge_path(achievement))

    assert response["Cache-Control"] == f"public, max-age={VERSIONED_MAX_AGE_SECONDS}, immutable"


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["", f"?{VERSION_PARAM}=stale"])
def test_unversioned_or_stale_url_is_cached_briefly(client, achievement, query):
    response = client.get(f"/Badge/{badge_name(achievement)}.png{query}")

    assert response.status_code == HTTPStatus.OK
    assert response["Cache-Control"] == f"public, max-age={UNVERSIONED_MAX_AGE_SECONDS}"


# --- Game icons ---


@pytest.mark.django_db
def test_game_icon_serves_the_uploaded_icon_as_a_96px_png(client, game):
    game.icon = _png_upload("crash.png", BLUE)
    game.save()

    image = _image(client.get(versioned_game_icon_path(game)))

    assert image.size == (GAME_ICON_SIZE_PX, GAME_ICON_SIZE_PX)
    assert image.getpixel((0, 0)) == BLUE


@pytest.mark.django_db
def test_game_icon_serves_the_placeholder_without_an_upload(client, game):
    image = _image(client.get(f"/Images/{game_image_name(game)}.png"))

    assert image.tobytes() == placeholder_image(GAME_ICON_SIZE_PX).tobytes()


@pytest.mark.django_db
def test_game_icon_path_changes_when_an_icon_is_uploaded(game):
    placeholder_path = versioned_game_icon_path(game)

    game.icon = _png_upload("crash.png", BLUE)
    game.save()

    assert versioned_game_icon_path(game) != placeholder_path


@pytest.mark.django_db
def test_fallback_game_icon_resolves_without_a_game(client):
    image = _image(client.get(f"/Images/{FALLBACK_GAME_IMAGE_NAME}.png"))

    assert image.size == (GAME_ICON_SIZE_PX, GAME_ICON_SIZE_PX)


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["999999", "1", "000000"])
def test_game_icon_unknown_or_non_canonical_name_is_not_found(client, game, name):
    assert client.get(f"/Images/{name}.png").status_code == HTTPStatus.NOT_FOUND


# --- Avatars ---


@pytest.mark.django_db
def test_user_pic_serves_a_deterministic_identicon(client):
    User.objects.create_user(username="crash.fan", password="pw")

    first = client.get(avatar_path("crash.fan"))
    second = client.get("/UserPic/crash.fan.png")

    assert _image(first).size == (AVATAR_SIZE_PX, AVATAR_SIZE_PX)
    assert first.content == second.content


@pytest.mark.django_db
def test_user_pics_differ_between_users(client):
    User.objects.create_user(username="alice", password="pw")
    User.objects.create_user(username="bob", password="pw")

    alice = client.get("/UserPic/alice.png")
    bob = client.get("/UserPic/bob.png")

    assert alice.content != bob.content


@pytest.mark.django_db
def test_user_pic_unknown_user_is_not_found(client):
    assert client.get("/UserPic/nobody.png").status_code == HTTPStatus.NOT_FOUND
