"""Achievement revisions: one per real change from every write path."""

from http import HTTPStatus

import pytest
from django.contrib.admin.sites import site as admin_site
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.achievements.admin import BadgeAdmin
from apps.achievements.models import (
    PLACEHOLDER_BADGE_NAME,
    Achievement,
    AchievementRevision,
    Badge,
)
from apps.api.editor import achievement_upload_checksum
from apps.api.handlers import ACHIEVEMENT_FLAGS_UNOFFICIAL, API_TOKEN_LIFETIME
from apps.games.models import Console, Game

User = get_user_model()

PLAYSTATION_RA_ID = 12
PASSWORD = "pw-secret-123"
AUTHOR_TOKEN = "author-tok"
UNKNOWN_ID = 999_999
FIRST_TRIGGER = "0xH0001=1_0xH0002=2"
SECOND_TRIGGER = "0xH0001=1_0xH0002=3"
THIRD_TRIGGER = "0xH0001=1_0xH0002=3_d0xH0004=0"
ORIGINAL_POINTS = 5
NEW_POINTS = 10
ACHIEVEMENT_CHANGELIST_URL = "/admin/achievements/achievement/"


def _user(username, is_staff=False):
    return User.objects.create_user(username=username, password=PASSWORD, is_staff=is_staff)


@pytest.fixture
def author(db):
    user = _user("author")
    user.api_token = AUTHOR_TOKEN
    user.api_token_expires_at = timezone.now() + API_TOKEN_LIFETIME
    user.save(update_fields=["api_token", "api_token_expires_at"])
    return user


@pytest.fixture
def other(db):
    return _user("other")


@pytest.fixture
def staff(db):
    return _user("staff", is_staff=True)


@pytest.fixture
def game(db):
    console = Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


def _achievement(game, author, status=Achievement.STATUS_DRAFT, editor=None, **fields):
    achievement = Achievement(
        game=game,
        author=author,
        title="Beach",
        description="Clear the beach",
        points=ORIGINAL_POINTS,
        mem_addr=FIRST_TRIGGER,
        status=status,
        **fields,
    )
    achievement.save(editor=editor or author)
    return achievement


def _form(achievement, **changes):
    fields = {
        "title": achievement.title,
        "description": achievement.description,
        "points": achievement.points,
        "type": achievement.type,
        "mem_addr": achievement.mem_addr,
        "status": achievement.status,
    }
    fields.update(changes)
    return fields


def _edit(client, achievement, **changes):
    return client.post(
        reverse("achievement_edit", args=[achievement.game_id, achievement.pk]),
        _form(achievement, **changes),
    )


def _revisions(achievement):
    return list(achievement.revisions.all())


# --- Recording ---


def test_creating_an_achievement_records_its_first_revision(game, author):
    achievement = _achievement(game, author)

    [revision] = _revisions(achievement)
    assert revision.editor == author
    assert revision.revised_values() == achievement.revised_values()


def test_three_edits_on_the_site_record_three_revisions(client, game, author):
    achievement = _achievement(game, author)
    client.force_login(author)

    for changes in (
        {"mem_addr": SECOND_TRIGGER},
        {"mem_addr": THIRD_TRIGGER},
        {"title": "Beach, cleared"},
    ):
        response = _edit(client, achievement, **changes)
        assert response.status_code == HTTPStatus.FOUND
        achievement.refresh_from_db()

    created, *edits = _revisions(achievement)
    assert [revision.mem_addr for revision in edits] == [
        SECOND_TRIGGER,
        THIRD_TRIGGER,
        THIRD_TRIGGER,
    ]
    assert edits[-1].title == "Beach, cleared"
    assert {revision.editor for revision in edits} == {author}


def test_saving_without_a_change_records_no_revision(client, game, author):
    achievement = _achievement(game, author)
    client.force_login(author)

    response = _edit(client, achievement)
    achievement.save()

    assert response.status_code == HTTPStatus.FOUND
    assert len(_revisions(achievement)) == 1


def test_a_revision_snapshots_every_revised_field(client, game, author):
    badge = Badge.objects.create(image="badges/one.png")
    achievement = _achievement(game, author)
    achievement.badge_name = badge.name
    achievement.type = Achievement.TYPE_PROGRESSION
    achievement.points = NEW_POINTS
    achievement.save(editor=author)

    latest = _revisions(achievement)[-1]
    assert (latest.badge_name, latest.type, latest.points) == (
        badge.name,
        Achievement.TYPE_PROGRESSION,
        NEW_POINTS,
    )


def test_an_admin_change_records_a_revision_by_the_staff_member(
    admin_client, admin_user, game, author
):
    achievement = _achievement(game, author)

    response = admin_client.post(
        f"{ACHIEVEMENT_CHANGELIST_URL}{achievement.pk}/change/",
        {
            "game": game.pk,
            "author": author.pk,
            "title": achievement.title,
            "description": "Changed in the admin",
            "points": achievement.points,
            "mem_addr": achievement.mem_addr,
            "status": achievement.status,
            "badge_name": achievement.badge_name,
        },
    )

    assert response.status_code == HTTPStatus.FOUND
    latest = _revisions(achievement)[-1]
    assert (latest.description, latest.editor) == ("Changed in the admin", admin_user)


def test_an_admin_status_action_records_one_revision_per_changed_achievement(
    admin_client, admin_user, game, author
):
    draft = _achievement(game, author)
    published = _achievement(game, author, status=Achievement.STATUS_COMMUNITY)

    admin_client.post(
        ACHIEVEMENT_CHANGELIST_URL,
        {"action": "publish_as_community", "_selected_action": [draft.pk, published.pk]},
    )

    assert [revision.status for revision in _revisions(draft)] == [
        Achievement.STATUS_DRAFT,
        Achievement.STATUS_COMMUNITY,
    ]
    assert _revisions(draft)[-1].editor == admin_user
    assert len(_revisions(published)) == 1


def test_a_change_to_an_achievement_written_without_save_records_its_prior_state_first(
    game, author
):
    [achievement] = Achievement.objects.bulk_create(
        [
            Achievement(
                game=game,
                author=author,
                title="Seeded",
                description="From a seed",
                mem_addr=FIRST_TRIGGER,
            )
        ]
    )
    achievement.refresh_from_db()
    seeded_at = achievement.updated_at
    achievement.mem_addr = SECOND_TRIGGER
    achievement.save(editor=author)

    baseline, change = _revisions(achievement)
    assert (baseline.mem_addr, baseline.editor, baseline.created_at) == (
        FIRST_TRIGGER,
        None,
        seeded_at,
    )
    assert (change.mem_addr, change.editor) == (SECOND_TRIGGER, author)


def _upload(client, user, token, game, achievement_id=0, **overrides):
    """An uploadachievement signed as rcheevos signs it; `achievement_id` 0 creates one."""
    params = {
        "r": "uploadachievement",
        "u": user.username,
        "t": token,
        "a": achievement_id,
        "g": game.pk,
        "n": "Beach",
        "d": "Clear it",
        "m": FIRST_TRIGGER,
        "z": ORIGINAL_POINTS,
        "f": ACHIEVEMENT_FLAGS_UNOFFICIAL,
        "b": PLACEHOLDER_BADGE_NAME,
        "x": "",
        **overrides,
    }
    params["h"] = achievement_upload_checksum(
        user.username, achievement_id, params["m"], params["z"]
    )
    return client.post("/dorequest.php", params).json()


def test_uploadachievement_records_a_revision_per_upload_that_changes_it(client, game, author):
    created = _upload(client, author, AUTHOR_TOKEN, game)
    achievement_id = created["AchievementID"]
    _upload(client, author, AUTHOR_TOKEN, game, achievement_id, m=SECOND_TRIGGER)
    _upload(client, author, AUTHOR_TOKEN, game, achievement_id, m=SECOND_TRIGGER)

    revisions = list(AchievementRevision.objects.filter(achievement_id=achievement_id))
    assert [revision.mem_addr for revision in revisions] == [FIRST_TRIGGER, SECOND_TRIGGER]
    assert {revision.editor for revision in revisions} == {author}


# --- Badges ---


def test_a_badge_only_a_revision_uses_cannot_be_deleted(game, author, staff):
    badge = Badge.objects.create(image="badges/one.png")
    achievement = _achievement(game, author, badge_name=badge.name)
    achievement.badge_name = PLACEHOLDER_BADGE_NAME
    achievement.save(editor=author)
    request = RequestFactory().get("/")
    request.user = staff
    staff.is_superuser = True

    assert BadgeAdmin(Badge, admin_site).has_delete_permission(request, badge) is False
