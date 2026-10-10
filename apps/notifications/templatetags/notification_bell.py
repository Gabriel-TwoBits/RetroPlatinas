from django import template

from apps.notifications.display import POLL_SECONDS

register = template.Library()


@register.inclusion_tag("notifications/partials/bell.html", takes_context=True)
def notification_bell(context):
    """`{% notification_bell %}`: the header's bell for the logged-in user."""
    return {"unread": context["user"].notifications.unread().count(), "poll_seconds": POLL_SECONDS}
