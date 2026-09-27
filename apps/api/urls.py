from django.urls import path

from apps.api import views

urlpatterns = [
    path("dorequest.php", views.dorequest, name="dorequest"),
    path("doupload.php", views.doupload, name="doupload"),
    path("api/test/presence/<str:username>/", views.debug_presence, name="test-presence"),
    path("api/users/<str:username>/", views.user_summary, name="api-user"),
    path("api/users/<str:username>/recent/", views.user_recent_unlocks, name="api-user-recent"),
    path(
        "api/games/<int:game_id>/leaderboard/<int:leaderboard_id>/",
        views.game_leaderboard,
        name="api-game-leaderboard",
    ),
    path("api/games/<int:game_id>/players/", views.game_players, name="api-game-players"),
]
