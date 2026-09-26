import re

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

MD5_HEX_DIGITS = 32
LOWERCASE_HEX = re.compile(r"[0-9a-f]+")


class Console(models.Model):
    ra_id = models.IntegerField(unique=True, verbose_name=_("RA ID"))
    name = models.CharField(max_length=64, verbose_name=_("name"))
    short_name = models.CharField(max_length=16, verbose_name=_("short name"))

    class Meta:
        verbose_name = _("console")
        verbose_name_plural = _("consoles")
        ordering = ["ra_id"]

    def __str__(self):
        return self.name


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
            raise ValidationError({"md5": _("Enter an MD5 hash: 32 hexadecimal digits.")})

    def save(self, *args, **kwargs):
        self.md5 = self.md5.lower()
        super().save(*args, **kwargs)
