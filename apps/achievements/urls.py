from django.urls import path

from apps.achievements import views

urlpatterns = [
    path(
        "games/<int:game_id>/achievements/new/",
        views.new_achievement,
        name="achievement_new",
    ),
    path(
        "games/<int:game_id>/achievements/<int:achievement_id>/edit/",
        views.edit_achievement,
        name="achievement_edit",
    ),
    path(
        "games/<int:game_id>/achievements/<int:achievement_id>/history/",
        views.achievement_history,
        name="achievement_history",
    ),
    path(
        "games/<int:game_id>/achievements/<int:achievement_id>/history/<int:revision_id>/revert/",
        views.revert_achievement,
        name="achievement_revert",
    ),
    path("games/<int:game_id>/code-notes/", views.code_notes, name="code_notes"),
    path("games/<int:game_id>/code-notes/new/", views.new_code_note, name="code_note_new"),
    path(
        "games/<int:game_id>/code-notes/<int:note_id>/edit/",
        views.edit_code_note,
        name="code_note_edit",
    ),
    path(
        "games/<int:game_id>/code-notes/<int:note_id>/delete/",
        views.delete_code_note,
        name="code_note_delete",
    ),
]
