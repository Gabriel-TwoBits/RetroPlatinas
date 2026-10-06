from django.urls import path

from apps.core import views

urlpatterns = [
    path("", views.home, name="home"),
    path("feed/", views.feed, name="feed"),
    path("feed/list/", views.feed_list, name="feed_list"),
    path("docs/getting-started/", views.getting_started, name="getting_started"),
]
