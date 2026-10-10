"""Who may change what an editor wrote, shared by RAIntegration's uploads and the web editor."""

from apps.achievements.models import ACHIEVEMENT_POINT_VALUES


def can_edit(user, author_id):
    """Only its author or staff change what the author wrote."""
    return user.is_staff or author_id == user.pk


def settable_points(current_points):
    """The points an achievement now worth `current_points` may be given: RA's scale, plus the
    current value, which may lie outside it when the admin set it."""
    return ACHIEVEMENT_POINT_VALUES | {current_points}
