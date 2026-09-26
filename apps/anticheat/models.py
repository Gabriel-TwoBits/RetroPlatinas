from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class SuspiciousActivity(models.Model):
    """A request pattern flagged for manual review; flagging never blocks or bans the user."""

    class Kind(models.TextChoices):
        INVALID_SIGNATURE = "invalid_signature", _("Missing or invalid validation hash")
        RATE_LIMITED = "rate_limited", _("Unlock rate limit exceeded")
        UNLOCK_BURST = "unlock_burst", _("Many unlocks in a short window")
        EARLY_UNLOCK = "early_unlock", _("Unlock right after the session started")

    class ReviewStatus(models.TextChoices):
        PENDING = "pending", _("Pending")
        LEGIT = "legit", _("Legitimate")
        CHEATER = "cheater", _("Cheater")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="suspicious_activities",
        verbose_name=_("user"),
    )
    kind = models.CharField(max_length=32, choices=Kind.choices, verbose_name=_("kind"))
    detail = models.JSONField(default=dict, blank=True, verbose_name=_("detail"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("created at"))
    review_status = models.CharField(
        max_length=16,
        choices=ReviewStatus.choices,
        default=ReviewStatus.PENDING,
        verbose_name=_("review status"),
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_suspicious_activities",
        verbose_name=_("reviewed by"),
    )
    reviewed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("reviewed at"))

    class Meta:
        verbose_name = _("suspicious activity")
        verbose_name_plural = _("suspicious activities")
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.user} — {self.get_kind_display()}"
