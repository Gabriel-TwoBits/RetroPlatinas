from django.urls import re_path

from apps.images import views

# RA's image paths, which rcheevos builds from a badge, game image or user name.
urlpatterns = [
    re_path(r"^Badge/(?P<name>[0-9]+)_lock\.png$", views.badge_locked, name="badge-locked"),
    re_path(r"^Badge/(?P<name>[0-9]+)\.png$", views.badge, name="badge"),
    re_path(r"^Images/(?P<name>[0-9]+)\.png$", views.game_icon, name="game-icon"),
    re_path(r"^UserPic/(?P<username>[^/]+)\.png$", views.user_pic, name="user-pic"),
]
