from functools import wraps
from urllib.parse import urlsplit

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.achievements.editing import can_edit
from apps.achievements.models import Achievement
from apps.comments.forms import CommentForm
from apps.comments.models import Comment, target_fields
from apps.comments.threads import page_url, thread
from apps.games.models import Game


def _answer(request, target, form=None):
    """HTMX swaps in the re-rendered section. A plain form post, sent before htmx loaded,
    returns to the page; an invalid one is dropped, as the browser enforces the form's limits."""
    if request.headers.get("HX-Request") == "true":
        return render(
            request, "comments/partials/thread.html", {"thread": thread(target, request.user, form)}
        )
    else:
        return redirect(f"{page_url(target)}#comments")


def _login_required(view):
    """`login_required` that, for htmx, sends the browser to log in and back to the page's
    comments: the XHR would follow a 302 and swap the whole login page into the section."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        page = urlsplit(request.headers.get("HX-Current-URL", "")).path
        if request.user.is_authenticated:
            return view(request, *args, **kwargs)
        elif request.headers.get("HX-Request") == "true" and page:
            response = HttpResponse()
            response["HX-Redirect"] = redirect_to_login(f"{page}#comments")["Location"]
            return response
        else:
            return redirect_to_login(request.get_full_path())

    return wrapper


def _add(request, target):
    form = CommentForm(request.POST)
    if form.is_valid():
        Comment.objects.create(
            author=request.user, content=form.cleaned_data["content"], **target_fields(target)
        )
        return _answer(request, target)
    else:
        return _answer(request, target, form)


@_login_required
@require_POST
def add_game_comment(request, game_id):
    return _add(request, get_object_or_404(Game, pk=game_id))


@_login_required
@require_POST
def add_achievement_comment(request, game_id, achievement_id):
    # Another user's draft does not exist, so neither does its comments section.
    achievement = get_object_or_404(
        Achievement.objects.visible_to(request.user), pk=achievement_id, game_id=game_id
    )
    return _add(request, achievement)


@_login_required
@require_POST
def delete_comment(request, comment_id):
    """Only its author or staff delete a comment; one on a page the viewer cannot see is 404."""
    on_visible_target = Q(game__isnull=False) | Q(
        achievement__in=Achievement.objects.visible_to(request.user)
    )
    comment = get_object_or_404(
        Comment.objects.filter(on_visible_target).select_related("game", "achievement"),
        pk=comment_id,
    )
    if not can_edit(request.user, comment.author_id):
        raise PermissionDenied("Only the author or staff delete a comment.")
    else:
        comment.delete()
        return _answer(request, comment.target)
