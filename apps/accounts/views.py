from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import InvalidPage
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from apps.accounts.forms import ProfileForm, RegistrationForm
from apps.accounts.friends import follow_context, friends_context
from apps.accounts.models import Friendship
from apps.accounts.profile import VALID_TABS, profile_context
from apps.accounts.ranking import BOARD_CACHE_MINUTES, MODE_HARDCORE, VALID_MODES, board_html
from apps.core import htmx

User = get_user_model()


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("/")
    else:
        form = RegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


def user_detail(request, username):
    profile_user = get_object_or_404(User, username=username)
    context = {
        **profile_context(profile_user, request.user),
        **follow_context(profile_user, request.user),
    }
    return render(request, "accounts/profile.html", context)


def user_panel(request, username, tab):
    if tab not in VALID_TABS:
        raise Http404("Unknown profile tab")
    profile_user = get_object_or_404(User, username=username)
    context = profile_context(profile_user, request.user)
    return render(request, f"accounts/partials/panel-{tab}.html", context)


@require_safe
def user_friends(request, username):
    profile_user = get_object_or_404(User, username=username)
    return render(request, "accounts/friends.html", friends_context(profile_user))


def _follow_answer(request, profile_user):
    """HTMX swaps in the re-rendered follow control; a plain form post returns to the profile."""
    if htmx.is_htmx(request):
        return render(
            request,
            "accounts/partials/follow-control.html",
            follow_context(profile_user, request.user),
        )
    else:
        return redirect("user_detail", username=profile_user.username)


@htmx.login_required()
@require_POST
def follow(request, username):
    friend = get_object_or_404(User, username=username, is_active=True)
    if friend.pk == request.user.pk:
        return HttpResponseBadRequest(gettext("You cannot follow yourself."))
    else:
        Friendship.objects.get_or_create(user=request.user, friend=friend)
        return _follow_answer(request, friend)


@htmx.login_required()
@require_POST
def unfollow(request, username):
    friend = get_object_or_404(User, username=username)
    Friendship.objects.filter(user=request.user, friend=friend).delete()
    return _follow_answer(request, friend)


@login_required
@require_http_methods(["GET", "POST"])
def edit_profile(request, username):
    profile_user = get_object_or_404(User, username=username)
    if request.user.pk != profile_user.pk:
        raise PermissionDenied("Only the owner edits a profile.")
    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile_user)
        if form.is_valid():
            # Only the bio: a full save would write back stale points and API token.
            form.save(commit=False).save(update_fields=["bio"])
            return redirect("user_detail", username=profile_user.username)
    else:
        form = ProfileForm(instance=profile_user)
    return render(
        request, "accounts/profile-edit.html", {"form": form, "profile_user": profile_user}
    )


def _ranking_page_number(request):
    try:
        return int(request.GET.get("page", 1))
    except ValueError as error:
        raise Http404("Unknown ranking page") from error


@require_safe
def ranking(request):
    mode = request.GET.get("mode", MODE_HARDCORE)
    if mode not in VALID_MODES:
        return HttpResponseBadRequest(gettext("Unknown ranking mode"))
    else:
        try:
            board = board_html(mode, _ranking_page_number(request))
        except InvalidPage as error:
            raise Http404("Unknown ranking page") from error
        return render(
            request,
            "accounts/ranking.html",
            {"board": board, "refresh_minutes": BOARD_CACHE_MINUTES},
        )
