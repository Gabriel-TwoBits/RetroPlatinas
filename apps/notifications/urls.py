from django.urls import path

from apps.notifications import views

urlpatterns = [
    path("notifications/", views.notification_list, name="notification_list"),
    path("notifications/unread/", views.unread_count, name="notification_unread_count"),
    path("notifications/menu/", views.notification_menu, name="notification_menu"),
    path("notifications/read/", views.read_all_notifications, name="notification_read_all"),
    path(
        "notifications/<int:notification_id>/read/",
        views.read_notification,
        name="notification_read",
    ),
]
