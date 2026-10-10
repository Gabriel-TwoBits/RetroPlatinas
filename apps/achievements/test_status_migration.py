"""The migrations from draft/community/verified to official/unofficial, forwards and backwards."""

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.games.models import Console, Game

User = get_user_model()

PLAYSTATION_RA_ID = 12
BEFORE = [("achievements", "0007_achievement_revision"), ("notifications", "0001_initial")]
AFTER = [
    ("achievements", "0008_official_and_unofficial_statuses"),
    ("notifications", "0002_official_and_unofficial_statuses"),
]
OLD_STATUSES = ("draft", "community", "verified")


@pytest.fixture
def restores_latest_schema():
    """Migrates forward again afterwards, so later tests see the current schema."""
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


def _migrate(targets):
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.mark.django_db(transaction=True)
def test_statuses_migrate_to_official_and_unofficial_and_back(restores_latest_schema):
    old_apps = _migrate(BEFORE)
    # Users and games keep their latest schema: only the two apps above were rolled back.
    author = User.objects.create_user(username="author")
    console = Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")
    game = Game.objects.create(title="Crash Bandicoot", console=console)
    old_achievement = old_apps.get_model("achievements", "Achievement")
    old_revision = old_apps.get_model("achievements", "AchievementRevision")
    old_notification = old_apps.get_model("notifications", "Notification")
    for status in OLD_STATUSES:
        achievement = old_achievement.objects.create(
            game_id=game.pk,
            author_id=author.pk,
            title=status,
            description="d",
            mem_addr="0xH0001=1",
            status=status,
        )
        old_revision.objects.create(
            achievement=achievement,
            title=status,
            description="d",
            points=0,
            mem_addr="0xH0001=1",
            badge_name="00000",
            status=status,
        )
    old_notification.objects.create(
        user_id=author.pk,
        kind="status",
        params={"achievement": "draft", "old_status": "draft", "new_status": "community"},
        target_url="/",
    )

    new_apps = _migrate(AFTER)
    achievements = new_apps.get_model("achievements", "Achievement").objects
    revisions = new_apps.get_model("achievements", "AchievementRevision").objects
    notification = new_apps.get_model("notifications", "Notification").objects.get()

    expected = {"draft": "unofficial", "community": "official", "verified": "official"}
    assert dict(achievements.values_list("title", "status")) == expected
    assert dict(revisions.values_list("title", "status")) == expected
    assert (notification.params["old_status"], notification.params["new_status"]) == (
        "unofficial",
        "official",
    )

    old_apps = _migrate(BEFORE)
    achievements = old_apps.get_model("achievements", "Achievement").objects
    notification = old_apps.get_model("notifications", "Notification").objects.get()

    # The verified seal is gone for good: it comes back as community.
    assert dict(achievements.values_list("title", "status")) == {
        "draft": "draft",
        "community": "community",
        "verified": "community",
    }
    assert (notification.params["old_status"], notification.params["new_status"]) == (
        "draft",
        "community",
    )
