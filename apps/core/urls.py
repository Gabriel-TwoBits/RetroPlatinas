from django.urls import path

from apps.core import views
from apps.core.docs import GETTING_STARTED

urlpatterns = [
    path("", views.home, name="home"),
    path("feed/", views.feed, name="feed"),
    path("feed/list/", views.feed_list, name="feed_list"),
    path("docs/", views.docs_index, name="docs"),
    # Named on its own: the home, the feed and the profile link the guide.
    path(
        f"docs/{GETTING_STARTED}/",
        views.docs_page,
        {"slug": GETTING_STARTED},
        name="getting_started",
    ),
    path("docs/<slug:slug>/", views.docs_page, name="docs_page"),
]
