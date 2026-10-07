from django.urls import path

from apps.comments import views

urlpatterns = [
    path("games/<int:game_id>/comments/", views.add_game_comment, name="game_comment_add"),
    path(
        "games/<int:game_id>/achievements/<int:achievement_id>/comments/",
        views.add_achievement_comment,
        name="achievement_comment_add",
    ),
    path("comments/<int:comment_id>/delete/", views.delete_comment, name="comment_delete"),
]
