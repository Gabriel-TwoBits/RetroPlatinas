from django.urls import path

from apps.api import views

urlpatterns = [
    path("dorequest.php", views.dorequest, name="dorequest"),
]
