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
]
