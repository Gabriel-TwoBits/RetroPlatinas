from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.achievements.editing import can_edit
from apps.achievements.models import Achievement
from apps.comments.forms import CommentForm
from apps.comments.models import Comment, target_fields
from apps.comments.threads import page_url, thread
from apps.core.htmx import is_htmx, login_required
from apps.games.models import Game
from apps.notifications.emit import notify_comment


def _answer(request, target, form=None):
    """HTMX swaps in the re-rendered section. A plain form post, sent before htmx loaded,
    returns to the page; an invalid one is dropped, as the browser enforces the form's limits."""
    if is_htmx(request):
        return render(
            request, "comments/partials/thread.html", {"thread": thread(target, request.user, form)}
        )
    else:
        return redirect(f"{page_url(target)}#comments")


def _add(request, target):
    form = CommentForm(request.POST)
    if form.is_valid():
        with transaction.atomic():
            comment = Comment.objects.create(
                author=request.user, content=form.cleaned_data["content"], **target_fields(target)
            )
            notify_comment(comment)
        return _answer(request, target)
    else:
        return _answer(request, target, form)


@login_required("#comments")
@require_POST
def add_game_comment(request, game_id):
    return _add(request, get_object_or_404(Game, pk=game_id))


@login_required("#comments")
@require_POST
def add_achievement_comment(request, game_id, achievement_id):
    achievement = get_object_or_404(
        Achievement.objects.select_related("author"),
        pk=achievement_id,
        game_id=game_id,
    )
    return _add(request, achievement)


@login_required("#comments")
@require_POST
def delete_comment(request, comment_id):
    """Only its author or staff delete a comment."""
    comment = get_object_or_404(
        Comment.objects.select_related("game", "achievement"),
        pk=comment_id,
    )
    if not can_edit(request.user, comment.author_id):
        raise PermissionDenied("Only the author or staff delete a comment.")
    else:
        comment.delete()
        return _answer(request, comment.target)
