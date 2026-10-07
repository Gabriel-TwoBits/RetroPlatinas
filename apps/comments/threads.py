"""The comments section at the bottom of the game page and of the achievement page."""

from django.urls import reverse

from apps.achievements.editing import can_edit
from apps.achievements.models import Achievement
from apps.comments.forms import CommentForm
from apps.comments.models import Comment
from apps.games.models import Game
from apps.images.catalog import avatar_path


def page_url(target):
    """The page that shows `target`'s comments."""
    if isinstance(target, Game):
        return reverse("game_detail", args=[target.pk])
    elif isinstance(target, Achievement):
        return reverse("achievement_detail", args=[target.game_id, target.pk])
    else:
        raise TypeError(f"Only games and achievements have comments, not {type(target)!r}")


def _add_url(target):
    if isinstance(target, Game):
        return reverse("game_comment_add", args=[target.pk])
    elif isinstance(target, Achievement):
        return reverse("achievement_comment_add", args=[target.game_id, target.pk])
    else:
        raise TypeError(f"Only games and achievements have comments, not {type(target)!r}")


def thread(target, viewer, form=None):
    """`target`'s comments oldest first, each with whether `viewer` may delete it (its author or
    staff), and the form to add one: `form` when it carries errors, else an empty one."""
    # TRADEOFF: every comment on one page; paginate once a thread reaches hundreds.
    comments = Comment.objects.on(target).select_related("author")
    return {
        "rows": [
            {
                "comment": comment,
                "avatar_url": avatar_path(comment.author.username),
                "delete_url": reverse("comment_delete", args=[comment.pk]),
                "deletable": can_edit(viewer, comment.author_id),
            }
            for comment in comments
        ],
        "add_url": _add_url(target),
        "page_url": page_url(target),
        "form": CommentForm() if form is None else form,
    }
