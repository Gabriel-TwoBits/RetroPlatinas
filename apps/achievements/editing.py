"""Who may change what an editor wrote, shared by RAIntegration's uploads and the web editor."""

from apps.achievements.models import Achievement


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
