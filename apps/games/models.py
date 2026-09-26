import re
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

MD5_HEX_DIGITS = 32
LOWERCASE_HEX = re.compile(r"[0-9a-f]+")

# rc_client renders rich presence into a 256-byte buffer, NUL terminator included.
RICH_PRESENCE_MAX_LENGTH = 255
# Twice rc_client's 120 s ping interval, so one lost ping still counts as continuous play.
PLAYTIME_MAX_PING_GAP = timedelta(minutes=4)
# A session with no ping for this long is over: rc_client stops pinging an idle emulator.
PLAYING_NOW_TTL = timedelta(minutes=5)


class ConsoleManager(models.Manager):
    def get_by_natural_key(self, ra_id):
        return self.get(ra_id=ra_id)


class Console(models.Model):
    ra_id = models.IntegerField(unique=True, verbose_name=_("RA ID"))
    name = models.CharField(max_length=64, verbose_name=_("name"))
    short_name = models.CharField(max_length=16, verbose_name=_("short name"))

    objects = ConsoleManager()

    class Meta:
        verbose_name = _("console")
        verbose_name_plural = _("consoles")
        ordering = ["ra_id"]

    def __str__(self):
        return self.name

    def natural_key(self):
        return (self.ra_id,)


class Game(models.Model):
    title = models.CharField(max_length=255, verbose_name=_("title"))
    console = models.ForeignKey(
        Console,
        on_delete=models.PROTECT,
        related_name="games",
        verbose_name=_("console"),
    )
    icon = models.ImageField(upload_to="games/", null=True, blank=True, verbose_name=_("icon"))
    description = models.TextField(blank=True, verbose_name=_("description"))
    rich_presence_patch = models.TextField(blank=True, verbose_name=_("rich presence patch"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("created at"))

    class Meta:
        verbose_name = _("game")
        verbose_name_plural = _("games")
        ordering = ["title"]

    def __str__(self):
        return self.title


class GameHash(models.Model):
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="hashes",
        verbose_name=_("game"),
    )
    md5 = models.CharField(
        max_length=MD5_HEX_DIGITS, unique=True, db_index=True, verbose_name=_("MD5")
    )
    label = models.CharField(max_length=128, verbose_name=_("label"))

    class Meta:
        verbose_name = _("game hash")
        verbose_name_plural = _("game hashes")

    def __str__(self):
        return f"{self.label} ({self.md5})"

    def clean(self):
        super().clean()
        self.md5 = self.md5.lower()
        if len(self.md5) != MD5_HEX_DIGITS or not LOWERCASE_HEX.fullmatch(self.md5):
            raise ValidationError(
                {
                    "md5": ValidationError(
                        _("Enter an MD5 hash: %(digits)s hexadecimal digits."),
                        params={"digits": MD5_HEX_DIGITS},
                    )
                }
            )

    # TRADEOFF: lowercased in Python only; update()/bulk_create/loaddata and rows stored in
    # uppercase escape it. A data migration plus CheckConstraint(md5=Lower("md5")) closes it.
    def save(self, *args, **kwargs):
        self.md5 = self.md5.lower()
        super().save(*args, **kwargs)


class PlayerGameQuerySet(models.QuerySet):
    def playing_now(self):
        """Sessions whose client pinged within `PLAYING_NOW_TTL`."""
        return self.filter(last_ping_at__gte=timezone.now() - PLAYING_NOW_TTL)


class PlayerGame(models.Model):
    """A user's play record for one game, kept up to date by the emulator's session requests."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="played_games",
        verbose_name=_("user"),
    )
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="players",
        verbose_name=_("game"),
    )
    first_played_at = models.DateTimeField(default=timezone.now, verbose_name=_("first played at"))
    last_played_at = models.DateTimeField(default=timezone.now, verbose_name=_("last played at"))
    playtime_seconds = models.PositiveIntegerField(default=0, verbose_name=_("playtime (seconds)"))
    last_rich_presence = models.CharField(
        max_length=RICH_PRESENCE_MAX_LENGTH, blank=True, verbose_name=_("last rich presence")
    )
    last_ping_at = models.DateTimeField(null=True, blank=True, verbose_name=_("last ping at"))
    hardcore = models.BooleanField(default=False, verbose_name=_("hardcore session"))

    objects = PlayerGameQuerySet.as_manager()

    class Meta:
        verbose_name = _("player game")
        verbose_name_plural = _("player games")
        ordering = ["-last_played_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "game"], name="games_playergame_user_game_unique"
            ),
        ]

    def __str__(self):
        return f"{self.user} — {self.game}"

    def record_ping(self, now):
        """Marks the session live at `now`, crediting the time since the previous contact.

        A gap longer than `PLAYTIME_MAX_PING_GAP` means the session was interrupted
        (emulator paused, closed or offline), so it credits nothing.
        """
        if self.last_ping_at is None:
            credited = timedelta(0)
        elif timedelta(0) <= now - self.last_ping_at <= PLAYTIME_MAX_PING_GAP:
            credited = now - self.last_ping_at
        else:
            credited = timedelta(0)
        self.playtime_seconds += round(credited.total_seconds())
        self.last_ping_at = now
