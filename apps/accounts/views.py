from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.forms import ProfileForm, RegistrationForm
from apps.accounts.profile import VALID_TABS, profile_context

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
    return render(request, "accounts/profile.html", profile_context(profile_user, request.user))


def user_panel(request, username, tab):
    if tab not in VALID_TABS:
        raise Http404("Unknown profile tab")
    profile_user = get_object_or_404(User, username=username)
    context = profile_context(profile_user, request.user)
    return render(request, f"accounts/partials/panel-{tab}.html", context)


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
