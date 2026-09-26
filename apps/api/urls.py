from django.urls import path

from apps.api import views

urlpatterns = [
    path("dorequest.php", views.dorequest, name="dorequest"),
    path("api/test/presence/<str:username>/", views.debug_presence, name="test-presence"),
]
