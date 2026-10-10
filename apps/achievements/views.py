from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from apps.achievements.code_notes import (
    add_code_note,
    address_label,
    rewrite_code_note,
    search_code_notes,
    served_address,
)
from apps.achievements.editing import can_edit
from apps.achievements.forms import (
    AchievementForm,
    CodeNoteForm,
    CodeNoteSearchForm,
    NewCodeNoteForm,
)
from apps.achievements.models import Achievement, Badge, CodeNote
from apps.achievements.revisions import can_revert, history, revert
from apps.achievements.scoring import SCORED_FIELDS, recalculate_unlocker_points
from apps.comments.threads import thread
from apps.core import stats
from apps.games.models import Game
from apps.images.catalog import badge_path


def _save(form, editor):
    """Saves the form's achievement, a new badge upload included, and recounts its unlockers'
    points when its status or points changed."""
    with transaction.atomic():
        achievement = form.save(commit=False)
        upload = form.cleaned_data["badge"]
        if upload is not None:
            achievement.badge_name = Badge.objects.create(image=upload, uploaded_by=editor).name
        achievement.save(editor=editor)
        if SCORED_FIELDS & set(form.changed_data):
            recalculate_unlocker_points([achievement.pk])
    return achievement


def _editor(request, achievement):
    if request.method == "POST":
        form = AchievementForm(request.POST, request.FILES, instance=achievement)
    else:
        form = AchievementForm(instance=achievement)

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


def _achievement(game_id, achievement_id):
    return get_object_or_404(
        Achievement.objects.select_related("game", "author"),
        pk=achievement_id,
        game_id=game_id,
    )


@require_safe
def achievement_detail(request, game_id, achievement_id):
    achievement = _achievement(game_id, achievement_id)
    return render(
        request,
        "achievements/detail.html",
        {
            "achievement": achievement,
            "game": achievement.game,
            "badge_url": badge_path(achievement.badge_name),
            "unlockers": stats.achievement_unlockers(achievement),
            "players": stats.game_players(achievement.game).count(),
            "editable": can_edit(request.user, achievement.author_id),
            "thread": thread(achievement, request.user),
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
    achievement = _achievement(game_id, achievement_id)
    if not can_edit(request.user, achievement.author_id):
        raise PermissionDenied("Only the author or staff edit an achievement.")
    else:
        return _editor(request, achievement)


@require_safe
def achievement_history(request, game_id, achievement_id):
    achievement = _achievement(game_id, achievement_id)
    return render(
        request,
        "achievements/history.html",
        {
            "achievement": achievement,
            "game": achievement.game,
            "entries": history(achievement, request.user),
            "editable": can_edit(request.user, achievement.author_id),
        },
    )


@login_required
@require_POST
@transaction.atomic
def revert_achievement(request, game_id, achievement_id, revision_id):
    # The lock serializes this revert with another change to the achievement.
    achievement = get_object_or_404(
        Achievement.objects.select_for_update(),
        pk=achievement_id,
        game_id=game_id,
    )
    revision = get_object_or_404(achievement.revisions, pk=revision_id)
    if not can_revert(request.user, achievement, revision):
        raise PermissionDenied("Only the author or staff revert, to points they may set.")
    else:
        revert(achievement, revision, request.user)
        messages.success(request, gettext("Achievement reverted."))
        return redirect("achievement_history", game_id=game_id, achievement_id=achievement.pk)


# --- Code notes ---


def _code_note(request, game_id, note_id):
    """The note `request.user` may change, else 404 for an unknown one and 403 for another's.

    A POST first locks the game row, as every code note writer does, so the note cannot be
    deleted between this read and the write; the caller runs inside a transaction.
    """
    if request.method == "POST":
        get_object_or_404(Game.objects.select_for_update(), pk=game_id)
    else:
        # Reading a note needs no lock.
        pass
    note = get_object_or_404(
        CodeNote.objects.select_related("game", "author", "updated_by"),
        pk=note_id,
        game_id=game_id,
    )
    if not can_edit(request.user, note.author_id):
        raise PermissionDenied("Only the author or staff change a code note.")
    else:
        return note


def _code_note_editor(request, game, form, note=None):
    return render(
        request,
        "achievements/code-note-edit.html",
        {
            "form": form,
            "game": game,
            "note": note,
            "address": None if note is None else address_label(note),
        },
    )


def _parent_page(request, view_name, game):
    """The same page on the parent game, which holds a subset's code notes."""
    url = reverse(view_name, kwargs={"game_id": game.parent_game_id})
    query = request.GET.urlencode()
    if query:
        return redirect(f"{url}?{query}")
    else:
        return redirect(url)


@require_safe
def code_notes(request, game_id):
    game = get_object_or_404(Game, pk=game_id)
    if game.is_subset:
        return _parent_page(request, "code_notes", game)
    search = CodeNoteSearchForm(request.GET)
    if not search.is_valid():
        return HttpResponseBadRequest(gettext("Invalid code note search"))
    else:
        query = search.cleaned_data["q"]
        # TRADEOFF: every matching note on one page; paginate if a game's notes reach thousands.
        rows = [
            {
                "address": served_address(address),
                "note": note,
                "editable": can_edit(request.user, note.author_id),
            }
            for address, note in search_code_notes(game, query)
        ]
        return render(
            request,
            "achievements/code-notes.html",
            {"game": game, "rows": rows, "query": query, "search": search},
        )


@login_required
@require_http_methods(["GET", "POST"])
def new_code_note(request, game_id):
    game = get_object_or_404(Game, pk=game_id)
    if game.is_subset:
        return _parent_page(request, "code_note_new", game)
    elif request.method == "POST":
        form = NewCodeNoteForm(request.POST)
    else:
        form = NewCodeNoteForm()

    if form.is_bound and form.is_valid():
        note = add_code_note(
            request.user, game, form.cleaned_data["address"], form.cleaned_data["note"]
        )
        if note is None:
            form.add_error(
                "address", gettext("This game already has a note at this address: edit it.")
            )
            return _code_note_editor(request, game, form)
        else:
            messages.success(request, gettext("Code note added."))
            return redirect("code_notes", game_id=game.pk)
    else:
        return _code_note_editor(request, game, form)


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_code_note(request, game_id, note_id):
    note = _code_note(request, game_id, note_id)
    if request.method == "POST":
        form = CodeNoteForm(request.POST)
    else:
        form = CodeNoteForm(initial={"note": note.note})

    if form.is_bound and form.is_valid():
        rewrite_code_note(note, request.user, form.cleaned_data["note"])
        messages.success(request, gettext("Code note saved."))
        return redirect("code_notes", game_id=note.game_id)
    else:
        return _code_note_editor(request, note.game, form, note)


@login_required
@require_POST
@transaction.atomic
def delete_code_note(request, game_id, note_id):
    note = _code_note(request, game_id, note_id)
    note.delete()
    messages.success(request, gettext("Code note deleted."))
    return redirect("code_notes", game_id=note.game_id)
