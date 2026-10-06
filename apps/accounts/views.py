from django.contrib.auth import get_user_model, login
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.forms import RegistrationForm
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
