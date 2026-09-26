from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.games.models import Game


class Achievement(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_COMMUNITY = "community"
    STATUS_VERIFIED = "verified"
    STATUS_CHOICES = [
        (STATUS_DRAFT, _("Draft")),
        (STATUS_COMMUNITY, _("Community")),
        (STATUS_VERIFIED, _("Verified")),
    ]
    # Served to every client as official, awarded and worth points; a draft is served
    # only to its author, as unofficial, and is never awarded.
    PUBLISHED_STATUSES = (STATUS_COMMUNITY, STATUS_VERIFIED)

    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="achievements",
        verbose_name=_("game"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name=_("author"),
    )
    title = models.CharField(max_length=255, verbose_name=_("title"))
    description = models.TextField(verbose_name=_("description"))
    points = models.IntegerField(default=0, verbose_name=_("points"))
    mem_addr = models.TextField(verbose_name=_("memory address expression"))
    badge = models.ImageField(upload_to="badges/", null=True, blank=True, verbose_name=_("badge"))
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        verbose_name=_("status"),
    )
    flags = models.IntegerField(default=5, verbose_name=_("flags"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("created at"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("updated at"))

    class Meta:
        verbose_name = _("achievement")
        verbose_name_plural = _("achievements")
        ordering = ["game", "title"]

    def __str__(self):
        return f"{self.title} ({self.game})"


class UserUnlock(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="unlocks",
        verbose_name=_("user"),
    )
    achievement = models.ForeignKey(
        Achievement,
        on_delete=models.CASCADE,
        verbose_name=_("achievement"),
    )
    hardcore = models.BooleanField(default=False, verbose_name=_("hardcore"))
    unlocked_at = models.DateTimeField(auto_now_add=True, verbose_name=_("unlocked at"))

    class Meta:
        verbose_name = _("user unlock")
        verbose_name_plural = _("user unlocks")
        unique_together = [("user", "achievement", "hardcore")]

    def __str__(self):
        mode = _("hardcore") if self.hardcore else _("softcore")
        return f"{self.user} — {self.achievement} ({mode})"


class CodeNote(models.Model):
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="code_notes",
        verbose_name=_("game"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name=_("author"),
    )
    address = models.CharField(max_length=16, verbose_name=_("address"))
    note = models.TextField(verbose_name=_("note"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("updated at"))

    class Meta:
        verbose_name = _("code note")
        verbose_name_plural = _("code notes")
        ordering = ["game", "address"]

    def __str__(self):
        return f"{self.address} ({self.game})"
