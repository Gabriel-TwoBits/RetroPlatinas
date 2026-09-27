import io
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import translation
from PIL import Image

from apps.achievements.models import (
    MAX_BADGE_UPLOAD_BYTES,
    MAX_BADGE_UPLOAD_SIDE_PX,
    PLACEHOLDER_BADGE_NAME,
    Achievement,
    Badge,
    badge_name_for,
    validate_badge_image,
)
from apps.games.models import Console, Game
from apps.images.catalog import (
    FALLBACK_GAME_IMAGE_NAME,
    VERSION_PARAM,
    avatar_path,
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


def _image_upload(name, color, image_format, size=UPLOAD_SIZE_PX):
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), color[:3]).save(buffer, format=image_format)
    return SimpleUploadedFile(name, buffer.getvalue())


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


@pytest.fixture
def uploaded_badge(db):
    return Badge.objects.create(image=_png_upload("boulders.png", RED))


def test_badge_names_are_zero_padded_numbers():
    assert badge_name_for(0) == PLACEHOLDER_BADGE_NAME
    assert badge_name_for(123) == "00123"
    assert badge_name_for(1234567) == "1234567"


@pytest.mark.django_db
def test_badges_are_named_in_upload_order():
    first = Badge.objects.create(image=_png_upload("first.png", RED))
    second = Badge.objects.create(image=_png_upload("second.png", BLUE))

    assert int(second.name) == int(first.name) + 1
    assert Badge.objects.named(second.name) == second


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["1", "001", "000001", "abcde", PLACEHOLDER_BADGE_NAME])
def test_badge_lookup_matches_only_canonical_names_of_uploads(uploaded_badge, name):
    assert Badge.objects.named(name) is None


@pytest.mark.django_db
def test_badge_serves_the_uploaded_badge_as_a_64px_png(client, uploaded_badge):
    image = _image(client.get(f"/Badge/{uploaded_badge.name}.png"))

    assert image.size == (BADGE_SIZE_PX, BADGE_SIZE_PX)
    assert image.getpixel((0, 0)) == RED


@pytest.mark.django_db
def test_badge_number_issued_again_serves_its_new_upload(client, uploaded_badge):
    number, name = uploaded_badge.pk, uploaded_badge.name
    _image(client.get(f"/Badge/{name}.png"))
    uploaded_badge.delete()
    Badge.objects.create(pk=number, image=_png_upload("reissued.png", BLUE))

    image = _image(client.get(f"/Badge/{name}.png"))

    assert image.getpixel((0, 0)) == BLUE


@pytest.mark.django_db
def test_placeholder_badge_name_serves_the_placeholder(client):
    image = _image(client.get(f"/Badge/{PLACEHOLDER_BADGE_NAME}.png"))

    assert image.tobytes() == placeholder_image(BADGE_SIZE_PX).tobytes()


@pytest.mark.django_db
def test_achievement_without_a_badge_serves_the_placeholder(client, achievement):
    assert achievement.badge_name == PLACEHOLDER_BADGE_NAME

    image = _image(client.get(badge_path(achievement.badge_name)))

    assert image.tobytes() == placeholder_image(BADGE_SIZE_PX).tobytes()


@pytest.mark.django_db
def test_draft_badge_is_served_without_credentials_for_its_author_to_test(
    client, achievement, uploaded_badge
):
    achievement.status = Achievement.STATUS_DRAFT
    achievement.badge_name = uploaded_badge.name
    achievement.save()

    image = _image(client.get(badge_path(achievement.badge_name)))

    assert image.getpixel((0, 0)) == RED


@pytest.mark.django_db
def test_locked_badge_is_a_grayscale_variant(client, uploaded_badge):
    image = _image(client.get(f"/Badge/{uploaded_badge.name}_lock.png"))

    assert image.size == (BADGE_SIZE_PX, BADGE_SIZE_PX)
    assert all(r == g == b for r, g, b, _ in image.get_flattened_data())
    assert image.getpixel((0, 0)) != RED


@pytest.mark.django_db
def test_locked_placeholder_is_grayscale(client):
    image = _image(client.get(f"/Badge/{PLACEHOLDER_BADGE_NAME}_lock.png"))

    assert all(r == g == b for r, g, b, _ in image.get_flattened_data())


@pytest.mark.django_db
def test_each_badge_serves_its_own_locked_variant(client, uploaded_badge):
    blue = Badge.objects.create(image=_png_upload("blue.png", BLUE))

    red_locked = client.get(f"/Badge/{uploaded_badge.name}_lock.png").content
    blue_locked = client.get(f"/Badge/{blue.name}_lock.png").content

    assert blue_locked != red_locked


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/Badge/99999.png", "/Badge/99999_lock.png", "/Badge/1.png"])
def test_badge_unknown_or_non_canonical_name_is_not_found(client, uploaded_badge, path):
    assert client.get(path).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_badge_rejects_writes(client, uploaded_badge):
    response = client.post(f"/Badge/{uploaded_badge.name}.png")
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.parametrize(
    ("name", "image_format"), [("a.png", "PNG"), ("a.jpg", "JPEG"), ("a.gif", "GIF")]
)
def test_badge_image_accepts_png_jpeg_and_gif(name, image_format):
    validate_badge_image(_image_upload(name, RED, image_format))


@pytest.mark.parametrize(
    ("upload", "code"),
    [
        (SimpleUploadedFile("a.png", b"not an image"), "invalid_image"),
        (_image_upload("a.png", RED, "BMP"), "invalid_image"),
        (SimpleUploadedFile("a.png", b"0" * (MAX_BADGE_UPLOAD_BYTES + 1)), "file_too_large"),
        (_image_upload("a.png", RED, "PNG", size=MAX_BADGE_UPLOAD_SIDE_PX + 1), "image_too_large"),
    ],
)
def test_badge_image_rejects_other_files(upload, code):
    with pytest.raises(ValidationError) as error:
        validate_badge_image(upload)

    assert error.value.code == code


# --- Versioning and caching ---


@pytest.mark.django_db
def test_badge_path_differs_between_badges(uploaded_badge):
    other = Badge.objects.create(image=_png_upload("blue.png", BLUE))

    assert badge_path(uploaded_badge.name) != badge_path(other.name)
    assert badge_path(uploaded_badge.name) != badge_path(PLACEHOLDER_BADGE_NAME)
    assert badge_path(uploaded_badge.name).startswith(f"/Badge/{uploaded_badge.name}.png?")
    assert badge_path(uploaded_badge.name, locked=True).startswith(
        f"/Badge/{uploaded_badge.name}_lock.png?"
    )


@pytest.mark.django_db
@pytest.mark.parametrize("locked", [False, True])
def test_current_version_is_cached_for_good(client, uploaded_badge, locked):
    response = client.get(badge_path(uploaded_badge.name, locked=locked))

    assert response["Cache-Control"] == f"public, max-age={VERSIONED_MAX_AGE_SECONDS}, immutable"


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["", f"?{VERSION_PARAM}=stale"])
def test_unversioned_or_stale_url_is_cached_briefly(client, uploaded_badge, query):
    response = client.get(f"/Badge/{uploaded_badge.name}.png{query}")

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
def test_fallback_game_icon_stays_the_placeholder_when_game_1_has_an_icon(client):
    console = Console.objects.create(ra_id=12, name="PlayStation", short_name="PS1")
    first_game = Game.objects.create(
        pk=1, title="First", console=console, icon=_png_upload("first.png", BLUE)
    )

    image = _image(client.get(f"/Images/{FALLBACK_GAME_IMAGE_NAME}.png"))

    assert game_image_name(first_game) != FALLBACK_GAME_IMAGE_NAME
    assert image.tobytes() == placeholder_image(GAME_ICON_SIZE_PX).tobytes()
    assert _image(client.get(versioned_game_icon_path(first_game))).getpixel((0, 0)) == BLUE


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


# --- Admin ---


@pytest.fixture
def admin_client(client, db):
    admin = User.objects.create_superuser(username="admin", password="pw")
    client.force_login(admin)
    return client


@pytest.mark.django_db
def test_achievement_admin_shows_badge_thumbnails(admin_client, achievement):
    response = admin_client.get(f"/admin/achievements/achievement/{achievement.pk}/change/")

    content = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert badge_path(achievement.badge_name) in content.replace("&amp;", "&")
    assert badge_path(achievement.badge_name, locked=True) in content.replace("&amp;", "&")


@pytest.mark.django_db
def test_game_admin_shows_icon_thumbnail(admin_client, game):
    response = admin_client.get(f"/admin/games/game/{game.pk}/change/")

    assert response.status_code == HTTPStatus.OK
    assert versioned_game_icon_path(game) in response.content.decode().replace("&amp;", "&")


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/admin/achievements/achievement/", "/admin/games/game/"])
def test_admin_lists_show_thumbnails(admin_client, achievement, path):
    response = admin_client.get(path)

    assert response.status_code == HTTPStatus.OK
    assert "<img src=" in response.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/admin/achievements/achievement/add/", "/admin/games/game/add/"])
def test_admin_add_forms_render_without_a_preview(admin_client, path):
    response = admin_client.get(path)

    assert response.status_code == HTTPStatus.OK
    with translation.override(response["Content-Language"]):
        placeholder_text = translation.gettext("Available after saving.")
    assert placeholder_text in response.content.decode()


BADGE_CHANGELIST_URL = "/admin/achievements/badge/"


@pytest.mark.django_db
def test_badge_admin_upload_names_the_badge_and_records_the_uploader(admin_client):
    response = admin_client.post(
        f"{BADGE_CHANGELIST_URL}add/", {"image": _png_upload("new.png", RED)}
    )

    assert response.status_code == HTTPStatus.FOUND
    badge = Badge.objects.get()
    assert badge.uploaded_by.username == "admin"
    assert _image(admin_client.get(f"/Badge/{badge.name}.png")).getpixel((0, 0)) == RED


@pytest.mark.django_db
def test_badge_admin_rejects_a_file_that_is_not_an_image(admin_client):
    upload = SimpleUploadedFile("new.png", b"not an image")

    response = admin_client.post(f"{BADGE_CHANGELIST_URL}add/", {"image": upload})

    assert response.status_code == HTTPStatus.OK
    assert not Badge.objects.exists()


@pytest.mark.django_db
def test_badge_admin_never_replaces_or_deletes_an_uploaded_image(admin_client, uploaded_badge):
    response = admin_client.get(f"{BADGE_CHANGELIST_URL}{uploaded_badge.pk}/change/")

    assert response.status_code == HTTPStatus.OK
    assert 'type="file"' not in response.content.decode()
    delete_url = f"{BADGE_CHANGELIST_URL}{uploaded_badge.pk}/delete/"
    assert admin_client.post(delete_url, {"post": "yes"}).status_code == HTTPStatus.FORBIDDEN
    assert Badge.objects.filter(pk=uploaded_badge.pk).exists()


def _achievement_form(achievement, badge_name):
    return {
        "game": achievement.game_id,
        "author": achievement.author_id,
        "title": achievement.title,
        "description": achievement.description,
        "points": achievement.points,
        "mem_addr": achievement.mem_addr,
        "status": achievement.status,
        "badge_name": badge_name,
    }


@pytest.mark.django_db
def test_achievement_admin_sets_an_uploaded_badge(admin_client, achievement, uploaded_badge):
    response = admin_client.post(
        f"/admin/achievements/achievement/{achievement.pk}/change/",
        _achievement_form(achievement, uploaded_badge.name),
    )

    assert response.status_code == HTTPStatus.FOUND
    achievement.refresh_from_db()
    assert achievement.badge_name == uploaded_badge.name


@pytest.mark.django_db
@pytest.mark.parametrize("badge_name", ["99999", "123"])
def test_achievement_admin_rejects_a_badge_name_nothing_was_uploaded_as(
    admin_client, achievement, badge_name
):
    response = admin_client.post(
        f"/admin/achievements/achievement/{achievement.pk}/change/",
        _achievement_form(achievement, badge_name),
    )

    assert response.status_code == HTTPStatus.OK
    achievement.refresh_from_db()
    assert achievement.badge_name == PLACEHOLDER_BADGE_NAME


# --- Badge migration ---

BEFORE_BADGES = [("achievements", "0004_user_unlock_unlocked_at_default")]
AFTER_BADGES = [("achievements", "0005_badge_and_achievement_badge_name")]


@pytest.fixture
def restores_latest_schema():
    """Migrates forward again afterwards, so later tests see the current schema."""
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.mark.django_db(transaction=True)
def test_badge_migration_keeps_each_uploaded_badge_under_its_old_name(restores_latest_schema):
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE_BADGES)
    old_apps = executor.loader.project_state(BEFORE_BADGES).apps
    author = old_apps.get_model("accounts", "User").objects.create(username="author")
    console = old_apps.get_model("games", "Console").objects.create(
        ra_id=12, name="PlayStation", short_name="PS1"
    )
    game = old_apps.get_model("games", "Game").objects.create(title="Crash", console=console)
    Achievement = old_apps.get_model("achievements", "Achievement")
    with_upload, without_upload = (
        Achievement.objects.create(
            game=game,
            author=author,
            title=title,
            description="d",
            mem_addr="0xH0001=1",
            badge=badge,
        )
        for title, badge in (("Uploaded", "badges/old.png"), ("Placeholder", ""))
    )

    executor = MigrationExecutor(connection)
    executor.migrate(AFTER_BADGES)
    new_apps = executor.loader.project_state(AFTER_BADGES).apps
    migrated = new_apps.get_model("achievements", "Achievement").objects.in_bulk()
    HistoricalBadge = new_apps.get_model("achievements", "Badge")

    assert migrated[with_upload.pk].badge_name == badge_name_for(with_upload.pk)
    assert migrated[without_upload.pk].badge_name == PLACEHOLDER_BADGE_NAME
    assert HistoricalBadge.objects.get(pk=with_upload.pk).image.name == "badges/old.png"
    assert HistoricalBadge.objects.create(image="badges/new.png").pk > with_upload.pk
