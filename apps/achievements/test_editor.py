"""The web achievement editor: creating and editing achievements on the site, the mem_addr check
through the vendored rcheevos parser, and what reaches the emulator afterwards."""

import io
import subprocess
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from apps.achievements import triggers
from apps.achievements.models import PLACEHOLDER_BADGE_NAME, Achievement, Badge, UserUnlock
from apps.api.handlers import (
    ACHIEVEMENT_FLAGS_CORE,
    ACHIEVEMENT_FLAGS_UNOFFICIAL,
    API_TOKEN_LIFETIME,
)
from apps.games.models import Console, Game
from apps.images.catalog import badge_path
from apps.images.rendering import BADGE_SIZE_PX

User = get_user_model()

PLAYSTATION_RA_ID = 12
PASSWORD = "pw-secret-123"
AUTHOR = "author"
AUTHOR_TOKEN = "author-tok"
OTHER = "other"
OTHER_TOKEN = "other-tok"
STAFF = "staff"
UNKNOWN_ID = 999_999
VALID_TRIGGER = "0xH61998=1_d0xH61998=0"
# rcheevos rejects `Z` as a memory size.
INVALID_TRIGGER = "0xHZZ=1"
INVALID_TRIGGER_REASON = "Invalid memory operand"
LEADERBOARD_DEFINITION = "STA:0xH0001=1::CAN:0=1::SUB:0xH0002=1::VAL:0xH0003"
MULTILINE_TRIGGER = "0xH0001=1\n0xH0002=1"
ORIGINAL_POINTS = 5
NEW_POINTS = 10
# Off RA's scale: only the admin sets such a value.
OFF_SCALE_POINTS = 7


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    cache.clear()


def _user(username, token=None, is_staff=False):
    user = User.objects.create_user(username=username, password=PASSWORD, is_staff=is_staff)
    if token is not None:
        user.api_token = token
        user.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
        user.save(update_fields=["api_token", "api_token_expires_at"])
    return user


@pytest.fixture
def author(db):
    return _user(AUTHOR, AUTHOR_TOKEN)


@pytest.fixture
def other(db):
    return _user(OTHER, OTHER_TOKEN)


@pytest.fixture
def staff(db):
    return _user(STAFF, is_staff=True)


@pytest.fixture
def game(db):
    console = Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


def _achievement(game, author, status=Achievement.STATUS_UNOFFICIAL, points=ORIGINAL_POINTS):
    return Achievement.objects.create(
        game=game,
        author=author,
        title="Old title",
        description="Old description",
        points=points,
        mem_addr="0xH0001=1",
        status=status,
    )


def _new_url(game):
    return reverse("achievement_new", args=[game.pk])


def _edit_url(achievement):
    return reverse("achievement_edit", args=[achievement.game_id, achievement.pk])


def _fields(**changes):
    fields = {
        "title": "Beach",
        "description": "Clear N. Sanity Beach",
        "points": NEW_POINTS,
        "type": Achievement.TYPE_PROGRESSION,
        "mem_addr": VALID_TRIGGER,
        "status": Achievement.STATUS_UNOFFICIAL,
    }
    fields.update(changes)
    return fields


def _post(client, url, **changes):
    return client.post(url, _fields(**changes), HTTP_ACCEPT_LANGUAGE="en")


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (BADGE_SIZE_PX, BADGE_SIZE_PX), "red").save(buffer, format="PNG")
    return SimpleUploadedFile("badge.png", buffer.getvalue(), content_type="image/png")


def _served(client, user, token, game):
    """The achievements `achievementsets` serves `user` for `game`, by id."""
    data = client.post(
        "/dorequest.php", {"r": "achievementsets", "u": user.username, "t": token, "g": game.pk}
    ).json()
    return {served["ID"]: served for served in data["Sets"][0]["Achievements"]}


# --- mem_addr check ---


def test_validate_trigger_accepts_a_trigger_rcheevos_parses():
    triggers.validate_trigger(VALID_TRIGGER)


def test_validate_trigger_carries_rcheevos_reason():
    with pytest.raises(ValidationError) as error:
        triggers.validate_trigger(INVALID_TRIGGER)

    assert error.value.code == "invalid_trigger"
    assert error.value.params == {"reason": INVALID_TRIGGER_REASON}


@pytest.mark.parametrize("mem_addr", [LEADERBOARD_DEFINITION, MULTILINE_TRIGGER, "Display:"])
def test_validate_trigger_refuses_what_the_checker_parses_as_something_else(mem_addr):
    with pytest.raises(ValidationError) as error:
        triggers.validate_trigger(mem_addr)

    assert error.value.code == "not_a_trigger"


def test_validate_trigger_refuses_a_condition_too_long_to_check():
    too_long = VALID_TRIGGER + "_0xH0001=1" * triggers.MAX_TRIGGER_BYTES

    with pytest.raises(ValidationError) as error:
        triggers.validate_trigger(too_long)

    assert error.value.code == "trigger_too_long"


def test_validate_trigger_reports_a_missing_checker(monkeypatch, tmp_path):
    monkeypatch.setattr(triggers, "MEM_ADDR_CHECKER", tmp_path / "missing.sh")

    with pytest.raises(ValidationError) as error:
        triggers.validate_trigger(VALID_TRIGGER)

    assert error.value.code == "checker_unavailable"


def test_validate_trigger_reports_a_checker_that_times_out(monkeypatch):
    def time_out(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(triggers.subprocess, "run", time_out)

    with pytest.raises(ValidationError) as error:
        triggers.validate_trigger(VALID_TRIGGER)

    assert error.value.code == "checker_unavailable"


# --- creating ---


@pytest.mark.django_db
def test_new_achievement_sends_an_anonymous_visitor_to_login(client, game):
    response = client.get(_new_url(game))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("login"))


@pytest.mark.django_db
def test_new_achievement_form_starts_unofficial(client, author, game):
    client.force_login(author)

    response = client.get(_new_url(game), HTTP_ACCEPT_LANGUAGE="en")

    assert response.status_code == HTTPStatus.OK
    assert response.context["form"]["status"].value() == Achievement.STATUS_UNOFFICIAL
    assert game.title in response.content.decode()


@pytest.mark.django_db
def test_new_achievement_for_an_unknown_game_is_not_found(client, author):
    client.force_login(author)

    response = client.get(reverse("achievement_new", args=[UNKNOWN_ID]))

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_creating_an_achievement_saves_it_unofficial_by_its_author(client, author, game):
    client.force_login(author)

    response = _post(client, _new_url(game))

    achievement = Achievement.objects.get()
    assert response.status_code == HTTPStatus.FOUND
    assert response.url == _edit_url(achievement)
    assert (achievement.game, achievement.author) == (game, author)
    assert achievement.status == Achievement.STATUS_UNOFFICIAL
    assert (achievement.title, achievement.description) == ("Beach", "Clear N. Sanity Beach")
    assert (achievement.points, achievement.type) == (NEW_POINTS, Achievement.TYPE_PROGRESSION)
    assert achievement.mem_addr == VALID_TRIGGER
    assert achievement.badge_name == PLACEHOLDER_BADGE_NAME


@pytest.mark.django_db
def test_an_author_may_create_an_achievement_already_official(client, author, other, game):
    client.force_login(author)

    _post(client, _new_url(game), status=Achievement.STATUS_OFFICIAL)

    achievement = Achievement.objects.get()
    assert achievement.status == Achievement.STATUS_OFFICIAL
    assert _served(client, other, OTHER_TOKEN, game)[achievement.pk]["Flags"] == (
        ACHIEVEMENT_FLAGS_CORE
    )


@pytest.mark.django_db
def test_a_created_achievement_is_listed_on_the_game_page_for_everyone(client, author, other, game):
    client.force_login(author)
    _post(client, _new_url(game))
    panel = reverse("game_panel", args=[game.pk, "achievements"])

    authors_view = client.get(panel, HTTP_ACCEPT_LANGUAGE="en")
    client.force_login(other)
    others_view = client.get(panel, HTTP_ACCEPT_LANGUAGE="en")

    assert "Beach" in authors_view.content.decode()
    assert "Beach" in others_view.content.decode()


@pytest.mark.django_db
def test_a_created_achievement_reaches_everyone_as_unofficial(client, author, other, game):
    client.force_login(author)
    _post(client, _new_url(game))
    achievement = Achievement.objects.get()

    for user, token in ((author, AUTHOR_TOKEN), (other, OTHER_TOKEN)):
        assert _served(client, user, token, game)[achievement.pk]["Flags"] == (
            ACHIEVEMENT_FLAGS_UNOFFICIAL
        )


@pytest.mark.django_db
def test_creating_rejects_a_condition_rcheevos_cannot_parse(client, author, game):
    client.force_login(author)

    response = _post(client, _new_url(game), mem_addr=INVALID_TRIGGER)

    assert response.status_code == HTTPStatus.OK
    assert response.context["form"].has_error("mem_addr", code="invalid_trigger")
    assert INVALID_TRIGGER_REASON in response.content.decode()
    assert not Achievement.objects.exists()


@pytest.mark.django_db
def test_creating_rejects_a_leaderboard_definition(client, author, game):
    client.force_login(author)

    response = _post(client, _new_url(game), mem_addr=LEADERBOARD_DEFINITION)

    assert response.context["form"].has_error("mem_addr", code="not_a_trigger")
    assert not Achievement.objects.exists()


@pytest.mark.django_db
def test_creating_rejects_points_off_the_scale(client, author, game):
    client.force_login(author)

    response = _post(client, _new_url(game), points=OFF_SCALE_POINTS)

    assert response.context["form"].has_error("points")
    assert not Achievement.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("status", ["draft", "community", "verified"])
def test_creating_rejects_a_status_other_than_official_or_unofficial(client, author, game, status):
    client.force_login(author)

    response = _post(client, _new_url(game), status=status)

    assert response.context["form"].has_error("status")
    assert not Achievement.objects.exists()


@pytest.mark.django_db
def test_creating_with_a_badge_upload_names_the_achievement_after_the_new_badge(
    client, author, game
):
    client.force_login(author)

    client.post(_new_url(game), {**_fields(), "badge": _png()})

    badge = Badge.objects.get()
    assert badge.uploaded_by == author
    assert Achievement.objects.get().badge_name == badge.name


@pytest.mark.django_db
def test_creating_rejects_a_badge_that_is_not_an_image(client, author, game):
    client.force_login(author)
    not_an_image = SimpleUploadedFile("badge.png", b"not an image", content_type="image/png")

    response = client.post(_new_url(game), {**_fields(), "badge": not_an_image})

    assert response.context["form"].has_error("badge", code="invalid_image")
    assert not Badge.objects.exists()
    assert not Achievement.objects.exists()


# --- editing ---


@pytest.mark.django_db
def test_edit_form_shows_the_author_and_the_last_update(client, author, game):
    achievement = _achievement(game, author)
    client.force_login(author)

    response = client.get(_edit_url(achievement), HTTP_ACCEPT_LANGUAGE="en")

    body = response.content.decode()
    assert response.status_code == HTTPStatus.OK
    assert reverse("user_detail", args=[AUTHOR]) in body
    assert timezone.localtime(achievement.updated_at).isoformat() in body
    assert badge_path(achievement.badge_name, locked=True) in body


@pytest.mark.django_db
def test_editing_persists_the_changes(client, author, game):
    achievement = _achievement(game, author)
    client.force_login(author)

    response = _post(client, _edit_url(achievement), title="New title", mem_addr=VALID_TRIGGER)

    achievement.refresh_from_db()
    assert response.status_code == HTTPStatus.FOUND
    assert achievement.title == "New title"
    assert achievement.points == NEW_POINTS
    assert achievement.mem_addr == VALID_TRIGGER
    assert achievement.author == author


@pytest.mark.django_db
def test_editing_keeps_the_badge_without_a_new_upload(client, author, game):
    badge = Badge.objects.create(image=_png())
    achievement = _achievement(game, author)
    achievement.badge_name = badge.name
    achievement.save()
    client.force_login(author)

    _post(client, _edit_url(achievement))

    achievement.refresh_from_db()
    assert achievement.badge_name == badge.name


@pytest.mark.django_db
def test_editing_keeps_points_off_the_scale_while_unchanged(client, author, game):
    achievement = _achievement(game, author, points=OFF_SCALE_POINTS)
    client.force_login(author)

    _post(client, _edit_url(achievement), points=OFF_SCALE_POINTS, title="Renamed")

    achievement.refresh_from_db()
    assert (achievement.title, achievement.points) == ("Renamed", OFF_SCALE_POINTS)


@pytest.mark.django_db
@pytest.mark.parametrize("status", [Achievement.STATUS_OFFICIAL, Achievement.STATUS_UNOFFICIAL])
def test_editing_another_users_achievement_is_forbidden(client, author, other, game, status):
    achievement = _achievement(game, author, status=status)
    client.force_login(other)

    get = client.get(_edit_url(achievement))
    post = _post(client, _edit_url(achievement), title="Hijacked")

    achievement.refresh_from_db()
    assert get.status_code == HTTPStatus.FORBIDDEN
    assert post.status_code == HTTPStatus.FORBIDDEN
    assert achievement.title == "Old title"


@pytest.mark.django_db
def test_editing_through_another_games_url_is_not_found(client, author, game):
    achievement = _achievement(game, author)
    other_game = Game.objects.create(title="Crash 2", console=game.console)
    client.force_login(author)

    response = client.get(reverse("achievement_edit", args=[other_game.pk, achievement.pk]))

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_editing_sends_an_anonymous_visitor_to_login(client, author, game):
    achievement = _achievement(game, author)

    response = client.get(_edit_url(achievement))

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.startswith(reverse("login"))


@pytest.mark.django_db
def test_staff_edit_any_achievement_and_make_it_official(client, author, staff, game):
    achievement = _achievement(game, author)
    client.force_login(staff)

    response = _post(client, _edit_url(achievement), status=Achievement.STATUS_OFFICIAL)

    achievement.refresh_from_db()
    assert response.status_code == HTTPStatus.FOUND
    assert achievement.status == Achievement.STATUS_OFFICIAL
    assert achievement.author == author


@pytest.mark.django_db
def test_the_editor_offers_an_author_both_statuses(client, author, game):
    achievement = _achievement(game, author, status=Achievement.STATUS_OFFICIAL)
    client.force_login(author)

    form = client.get(_edit_url(achievement)).context["form"]

    assert [value for value, _label in form.fields["status"].choices] == [
        Achievement.STATUS_OFFICIAL,
        Achievement.STATUS_UNOFFICIAL,
    ]


@pytest.mark.django_db
def test_making_an_achievement_official_serves_it_to_everyone_as_core(client, author, other, game):
    achievement = _achievement(game, author)
    client.force_login(author)

    _post(client, _edit_url(achievement), status=Achievement.STATUS_OFFICIAL)

    assert _served(client, other, OTHER_TOKEN, game)[achievement.pk]["Flags"] == (
        ACHIEVEMENT_FLAGS_CORE
    )


@pytest.mark.django_db
def test_making_an_official_achievement_unofficial_recounts_its_unlockers(
    client, author, other, game
):
    achievement = _achievement(game, author, status=Achievement.STATUS_OFFICIAL)
    UserUnlock.objects.create(user=other, achievement=achievement, hardcore=False)
    UserUnlock.objects.create(user=other, achievement=achievement, hardcore=True)
    User.objects.filter(pk=other.pk).update(
        softcore_points=ORIGINAL_POINTS, hardcore_points=ORIGINAL_POINTS
    )
    unlocks = set(UserUnlock.objects.values_list("pk", flat=True))
    client.force_login(author)

    _post(
        client, _edit_url(achievement), status=Achievement.STATUS_UNOFFICIAL, points=ORIGINAL_POINTS
    )

    other.refresh_from_db()
    assert (other.softcore_points, other.hardcore_points) == (0, 0)
    assert set(UserUnlock.objects.values_list("pk", flat=True)) == unlocks


@pytest.mark.django_db
def test_changing_an_official_achievements_points_recounts_its_unlockers(
    client, author, other, game
):
    achievement = _achievement(game, author, status=Achievement.STATUS_OFFICIAL)
    UserUnlock.objects.create(user=other, achievement=achievement, hardcore=False)
    User.objects.filter(pk=other.pk).update(softcore_points=ORIGINAL_POINTS)
    client.force_login(author)

    _post(client, _edit_url(achievement), status=Achievement.STATUS_OFFICIAL, points=NEW_POINTS)

    other.refresh_from_db()
    assert other.softcore_points == NEW_POINTS


# --- game page links ---


@pytest.mark.django_db
def test_game_page_offers_a_new_achievement_to_a_logged_in_user_only(client, author, game):
    anonymous = client.get(reverse("game_detail", args=[game.pk])).content.decode()
    client.force_login(author)
    logged_in = client.get(reverse("game_detail", args=[game.pk])).content.decode()

    assert _new_url(game) not in anonymous
    assert _new_url(game) in logged_in


@pytest.mark.django_db
def test_game_page_offers_edit_on_the_viewers_own_achievements_only(client, author, other, game):
    own = _achievement(game, author, status=Achievement.STATUS_OFFICIAL)
    others = _achievement(game, other, status=Achievement.STATUS_OFFICIAL)
    client.force_login(author)

    body = client.get(reverse("game_detail", args=[game.pk])).content.decode()

    assert _edit_url(own) in body
    assert _edit_url(others) not in body


@pytest.mark.django_db
def test_game_page_offers_staff_edit_on_every_achievement(client, author, staff, game):
    achievement = _achievement(game, author, status=Achievement.STATUS_OFFICIAL)
    client.force_login(staff)

    body = client.get(reverse("game_detail", args=[game.pk])).content.decode()

    assert _edit_url(achievement) in body
