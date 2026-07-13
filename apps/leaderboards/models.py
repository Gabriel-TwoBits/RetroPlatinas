from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.games.models import Game


class Leaderboard(models.Model):
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="leaderboards",
        verbose_name=_("game"),
    )
    title = models.CharField(max_length=255, verbose_name=_("title"))
    description = models.TextField(blank=True, verbose_name=_("description"))
    mem_addr = models.TextField(verbose_name=_("memory address expression"))
    format = models.CharField(max_length=16, default="VALUE", verbose_name=_("format"))
    lower_is_better = models.BooleanField(default=False, verbose_name=_("lower is better"))

    class Meta:
        verbose_name = _("leaderboard")
        verbose_name_plural = _("leaderboards")
        ordering = ["id"]

    def __str__(self):
        return f"{self.title} ({self.game})"


class LeaderboardEntry(models.Model):
    leaderboard = models.ForeignKey(
        Leaderboard,
        on_delete=models.CASCADE,
        related_name="entries",
        verbose_name=_("leaderboard"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        verbose_name=_("user"),
    )
    score = models.BigIntegerField(verbose_name=_("score"))
    submitted_at = models.DateTimeField(auto_now_add=True, verbose_name=_("submitted at"))

    class Meta:
        verbose_name = _("leaderboard entry")
        verbose_name_plural = _("leaderboard entries")
        unique_together = [("leaderboard", "user")]

    def __str__(self):
        return f"{self.user} — {self.leaderboard}: {self.score}"
