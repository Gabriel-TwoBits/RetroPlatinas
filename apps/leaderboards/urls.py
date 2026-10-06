from django.urls import path

from apps.leaderboards import views

urlpatterns = [
    path(
        "games/<int:game_id>/leaderboards/<int:leaderboard_id>/",
        views.leaderboard_detail,
        name="leaderboard_detail",
    ),
]
