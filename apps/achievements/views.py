from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext
from django.views.decorators.http import require_http_methods

from apps.achievements.editing import achievements_reachable_by, can_edit
from apps.achievements.forms import AchievementForm
from apps.achievements.models import Achievement, Badge
from apps.achievements.scoring import recalculate_unlocker_points
from apps.games.models import Game
from apps.images.catalog import badge_path

# What an unlocker's totals are counted from.
SCORED_FIELDS = frozenset({"status", "points"})


def _save(form, editor):
    """Saves the form's achievement, a new badge upload included, and recounts its unlockers'
    points when its status or points changed."""
    with transaction.atomic():
        achievement = form.save(commit=False)
        upload = form.cleaned_data["badge"]
        if upload is not None:
            achievement.badge_name = Badge.objects.create(image=upload, uploaded_by=editor).name
        achievement.save()
        if SCORED_FIELDS & set(form.changed_data):
            recalculate_unlocker_points([achievement.pk])
    return achievement


def _editor(request, achievement):
    if request.method == "POST":
        form = AchievementForm(
            request.POST, request.FILES, instance=achievement, editor=request.user
        )
    else:
        form = AchievementForm(instance=achievement, editor=request.user)

    if form.is_bound and form.is_valid():
        saved = _save(form, request.user)
        messages.success(request, gettext("Achievement saved."))
        return redirect("achievement_edit", game_id=saved.game_id, achievement_id=saved.pk)
    else:
        return render(
            request,
            "achievements/edit.html",
            {
                "form": form,
                "game": achievement.game,
                "badge_url": badge_path(achievement.badge_name),
                "locked_badge_url": badge_path(achievement.badge_name, locked=True),
            },
        )


@login_required
@require_http_methods(["GET", "POST"])
def new_achievement(request, game_id):
    game = get_object_or_404(Game, pk=game_id)
    return _editor(request, Achievement(game=game, author=request.user))


@login_required
@require_http_methods(["GET", "POST"])
def edit_achievement(request, game_id, achievement_id):
    achievement = get_object_or_404(
        achievements_reachable_by(request.user).select_related("game", "author"),
        pk=achievement_id,
        game_id=game_id,
    )
    if not can_edit(request.user, achievement.author_id):
        raise PermissionDenied("Only the author or staff edit an achievement.")
    else:
        return _editor(request, achievement)
