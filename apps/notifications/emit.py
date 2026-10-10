"""Creates the notifications an achievement's author receives. Nobody is notified of what they
did themselves, and an inactive account, which cannot log in to read them, is notified of nothing.

Imports nothing from the achievements app, which calls into it while recording revisions.
"""

from dataclasses import dataclass

from django.urls import reverse

from apps.notifications.models import Notification

COMMENTS_FRAGMENT = "#comments"


@dataclass(frozen=True)
class StatusChange:
    achievement_id: int
    game_id: int
    author_id: int
    author_is_active: bool
    title: str
    old_status: str
    new_status: str
    # The subset's title, empty for an achievement of a core set.
    set_title: str


def _achievement_url(game_id, achievement_id):
    return reverse("achievement_detail", args=[game_id, achievement_id])


def _achievement_params(title, set_title):
    """The achievement's title and, for a subset's, the subset's title under `set`."""
    if set_title:
        return {"achievement": title, "set": set_title}
    else:
        return {"achievement": title}


def subset_title(set_type, set_title):
    """The title a notification names a set by: a subset's, none for a core set, which may keep
    a `set_title` from when it was a subset."""
    if set_type is None:
        return ""
    else:
        return set_title


def _set_title(game):
    return subset_title(game.set_type, game.set_title)


def notify_comment(comment):
    """Tells the achievement's author about `comment`; a comment on a game notifies nobody."""
    achievement = comment.achievement
    if achievement is None:
        # Games have no author to notify.
        return None
    elif achievement.author_id == comment.author_id:
        return None
    elif not achievement.author.is_active:
        return None
    else:
        return Notification.objects.create(
            user_id=achievement.author_id,
            kind=Notification.KIND_COMMENT,
            params={
                "actor": comment.author.username,
                **_achievement_params(achievement.title, _set_title(achievement.game)),
            },
            target_url=_achievement_url(achievement.game_id, achievement.pk) + COMMENTS_FRAGMENT,
        )


def notify_unlock(achievement, player):
    """Tells the achievement's author that `player` unlocked it. One insert from values the award
    already holds (its query joins the author and the game), so the award path makes no extra
    read."""
    if achievement.author_id == player.pk:
        return None
    elif not achievement.author.is_active:
        return None
    else:
        return Notification.objects.create(
            user_id=achievement.author_id,
            kind=Notification.KIND_UNLOCK,
            params={
                "actor": player.username,
                **_achievement_params(achievement.title, _set_title(achievement.game)),
            },
            target_url=_achievement_url(achievement.game_id, achievement.pk),
        )


def notify_status_changes(changes, editor):
    """Tells each author that `editor` (`None` when unknown) changed their achievement's status."""
    Notification.objects.bulk_create(
        [
            Notification(
                user_id=change.author_id,
                kind=Notification.KIND_STATUS,
                params={
                    **_achievement_params(change.title, change.set_title),
                    "old_status": change.old_status,
                    "new_status": change.new_status,
                },
                target_url=_achievement_url(change.game_id, change.achievement_id),
            )
            for change in changes
            if change.author_is_active and (editor is None or editor.pk != change.author_id)
        ]
    )
