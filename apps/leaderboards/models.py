from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.games.models import Game


class Leaderboard(models.Model):
    class Format(models.TextChoices):
        """The leaderboard formats rcheevos' `rc_parse_format` recognises, by canonical name."""

        SCORE = "SCORE", _("Score (000000)")
        FRAMES = "FRAMES", _("Time (frames)")
        MILLISECS = "MILLISECS", _("Time (centiseconds)")
        SECS = "SECS", _("Time (seconds)")
        MINUTES = "MINUTES", _("Time (minutes)")
        SECS_AS_MINS = "SECS_AS_MINS", _("Time (seconds as minutes)")
        VALUE = "VALUE", _("Value")
        UNSIGNED = "UNSIGNED", _("Value (unsigned)")
        TENS = "TENS", _("Value (tens)")
        HUNDREDS = "HUNDREDS", _("Value (hundreds)")
        THOUSANDS = "THOUSANDS", _("Value (thousands)")
        FIXED1 = "FIXED1", _("Value (1 fixed decimal)")
        FIXED2 = "FIXED2", _("Value (2 fixed decimals)")
        FIXED3 = "FIXED3", _("Value (3 fixed decimals)")
        FLOAT1 = "FLOAT1", _("Decimal (1 digit)")
        FLOAT2 = "FLOAT2", _("Decimal (2 digits)")
        FLOAT3 = "FLOAT3", _("Decimal (3 digits)")
        FLOAT4 = "FLOAT4", _("Decimal (4 digits)")
        FLOAT5 = "FLOAT5", _("Decimal (5 digits)")
        FLOAT6 = "FLOAT6", _("Decimal (6 digits)")

    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="leaderboards",
        verbose_name=_("game"),
    )
    title = models.CharField(max_length=255, verbose_name=_("title"))
    description = models.TextField(blank=True, verbose_name=_("description"))
    mem_addr = models.TextField(verbose_name=_("memory address expression"))
    format = models.CharField(
        max_length=16, choices=Format.choices, default=Format.VALUE, verbose_name=_("format")
    )
    lower_is_better = models.BooleanField(default=False, verbose_name=_("lower is better"))
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("author"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("created at"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("updated at"))

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
