from django.urls import path

from apps.games import views

urlpatterns = [
    path("games/<int:game_id>/", views.game_detail, name="game_detail"),
    path("games/<int:game_id>/panel/<slug:tab>/", views.game_panel, name="game_panel"),
]
