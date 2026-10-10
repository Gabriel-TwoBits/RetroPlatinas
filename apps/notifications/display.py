"""What the bell's menu and the notifications page show: each notification's message, rendered in
the reader's language from its kind and parameters."""

from django.utils.translation import gettext

from apps.achievements.models import Achievement
from apps.notifications.models import Notification

# The bell's menu lists the latest notifications; the page lists them all.
MENU_NOTIFICATIONS_SHOWN = 10
NOTIFICATIONS_PER_PAGE = 50
POLL_SECONDS = 60


def _status_message(notification):
    params = notification.params
    if params["new_status"] == Achievement.STATUS_OFFICIAL:
        return gettext("Your achievement “%(achievement)s” is now official.") % params
    elif params["new_status"] == Achievement.STATUS_UNOFFICIAL:
        return gettext("Your achievement “%(achievement)s” is now unofficial.") % params
    else:
        raise ValueError(
            f"Notification {notification.pk} has unknown status {params['new_status']!r}"
        )


def message(notification):
    params = notification.params
    if notification.kind == Notification.KIND_COMMENT:
        return gettext("%(actor)s commented on your achievement “%(achievement)s”.") % params
    elif notification.kind == Notification.KIND_UNLOCK:
        return gettext("%(actor)s unlocked your achievement “%(achievement)s”.") % params
    elif notification.kind == Notification.KIND_STATUS:
        return _status_message(notification)
    else:
        raise ValueError(f"Notification {notification.pk} has unknown kind {notification.kind!r}")


def rows(notifications):
    return [
        {"notification": notification, "message": message(notification)}
        for notification in notifications
    ]


def menu_rows(user):
    """`user`'s latest notifications, newest first."""
    return rows(user.notifications.all()[:MENU_NOTIFICATIONS_SHOWN])
