from django.urls import path

from apps.core import views

urlpatterns = [
    path("", views.home, name="home"),
    path("docs/getting-started/", views.getting_started, name="getting_started"),
]
