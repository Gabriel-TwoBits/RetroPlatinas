from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

KIND_MAX_CHARS = 16
TARGET_URL_MAX_CHARS = 255


class NotificationQuerySet(models.QuerySet):
    def unread(self):
        return self.filter(read=False)


class Notification(models.Model):
    """Something that happened to one of `user`'s achievements.

    Stores the kind and its parameters, never the sentence: the message is rendered in the
    reader's language when shown (`apps.notifications.display`).
    """

    KIND_COMMENT = "comment"
    KIND_UNLOCK = "unlock"
    KIND_STATUS = "status"
    KIND_CHOICES = [
        (KIND_COMMENT, _("Comment on your achievement")),
        (KIND_UNLOCK, _("Unlock of your achievement")),
        (KIND_STATUS, _("Status change of your achievement")),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("user"),
    )
    kind = models.CharField(max_length=KIND_MAX_CHARS, choices=KIND_CHOICES, verbose_name=_("kind"))
    params = models.JSONField(default=dict, verbose_name=_("message parameters"))
    target_url = models.CharField(max_length=TARGET_URL_MAX_CHARS, verbose_name=_("target URL"))
    read = models.BooleanField(default=False, verbose_name=_("read"))
    created_at = models.DateTimeField(
        default=timezone.now, editable=False, verbose_name=_("created at")
    )

    objects = NotificationQuerySet.as_manager()

    class Meta:
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"{self.user} — {self.kind}"
