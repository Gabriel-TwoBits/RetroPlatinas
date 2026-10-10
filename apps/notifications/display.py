"""What the bell's menu and the notifications page show: each notification's message, rendered in
the reader's language from its kind and parameters."""

from django.utils.translation import gettext

from apps.achievements.models import Achievement
from apps.notifications.models import Notification

# The bell's menu lists the latest notifications; the page lists them all.
MENU_NOTIFICATIONS_SHOWN = 10
NOTIFICATIONS_PER_PAGE = 50
POLL_SECONDS = 60


def _status_template(notification, in_subset):
    params = notification.params
    if params["new_status"] == Achievement.STATUS_OFFICIAL and in_subset:
        return gettext("Your achievement “%(achievement)s” in the %(set)s subset is now official.")
    elif params["new_status"] == Achievement.STATUS_OFFICIAL:
        return gettext("Your achievement “%(achievement)s” is now official.")
    elif params["new_status"] == Achievement.STATUS_UNOFFICIAL and in_subset:
        return gettext(
            "Your achievement “%(achievement)s” in the %(set)s subset is now unofficial."
        )
    elif params["new_status"] == Achievement.STATUS_UNOFFICIAL:
        return gettext("Your achievement “%(achievement)s” is now unofficial.")
    else:
        raise ValueError(
            f"Notification {notification.pk} has unknown status {params['new_status']!r}"
        )


def _template(notification):
    """The message's translated template; an achievement of a subset carries the subset's
    title under `set`."""
    in_subset = "set" in notification.params
    if notification.kind == Notification.KIND_COMMENT and in_subset:
        return gettext(
            "%(actor)s commented on your achievement “%(achievement)s” in the %(set)s subset."
        )
    elif notification.kind == Notification.KIND_COMMENT:
        return gettext("%(actor)s commented on your achievement “%(achievement)s”.")
    elif notification.kind == Notification.KIND_UNLOCK and in_subset:
        return gettext(
            "%(actor)s unlocked your achievement “%(achievement)s” in the %(set)s subset."
        )
    elif notification.kind == Notification.KIND_UNLOCK:
        return gettext("%(actor)s unlocked your achievement “%(achievement)s”.")
    elif notification.kind == Notification.KIND_STATUS:
        return _status_template(notification, in_subset)
    else:
        raise ValueError(f"Notification {notification.pk} has unknown kind {notification.kind!r}")


def message(notification):
    return _template(notification) % notification.params


def rows(notifications):
    return [
        {"notification": notification, "message": message(notification)}
        for notification in notifications
    ]


def menu_rows(user):
    """`user`'s latest notifications, newest first."""
    return rows(user.notifications.all()[:MENU_NOTIFICATIONS_SHOWN])
