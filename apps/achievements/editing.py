"""Who may change what an editor wrote, shared by RAIntegration's uploads and the web editor."""

from apps.achievements.models import ACHIEVEMENT_POINT_VALUES, Achievement


def can_edit(user, author_id):
    """Only its author or staff change what the author wrote."""
    return user.is_staff or author_id == user.pk


def achievements_reachable_by(user):
    """The achievements `user` may look up to edit: staff reach every draft; to anyone else,
    another user's draft does not exist."""
    if user.is_staff:
        return Achievement.objects.all()
    else:
        return Achievement.objects.visible_to(user)


def settable_statuses(user, current_status):
    """The statuses `user` may give an achievement now in `current_status`: staff any; an
    author moves it between draft and community, and leaves the verified seal to staff."""
    if user.is_staff:
        return [status for status, _label in Achievement.STATUS_CHOICES]
    elif current_status == Achievement.STATUS_VERIFIED:
        return [Achievement.STATUS_VERIFIED]
    else:
        return [Achievement.STATUS_DRAFT, Achievement.STATUS_COMMUNITY]


def settable_points(current_points):
    """The points an achievement now worth `current_points` may be given: RA's scale, plus the
    current value, which may lie outside it when the admin set it."""
    return ACHIEVEMENT_POINT_VALUES | {current_points}
