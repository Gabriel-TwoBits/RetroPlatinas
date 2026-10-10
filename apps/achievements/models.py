import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from PIL import Image

from apps.games.models import Game
from apps.notifications.emit import StatusChange, notify_status_changes

BADGE_NAME_DIGITS = 5
# rc_client_achievement_t.badge_name is a char[8].
BADGE_NAME_MAX_CHARS = 7
BADGE_NAME_PATTERN = re.compile(rf"[0-9]{{{BADGE_NAME_DIGITS},{BADGE_NAME_MAX_CHARS}}}")
# RA's name for "no badge": served as the placeholder, never given to an upload.
PLACEHOLDER_BADGE_NAME = "0" * BADGE_NAME_DIGITS

BYTES_PER_MIB = 2**20
# RAWeb's limit for a badge upload.
MAX_BADGE_UPLOAD_BYTES = BYTES_PER_MIB
BADGE_UPLOAD_FORMATS = ("PNG", "JPEG", "GIF")
# Bounds the memory a small compressed upload can take once decoded.
MAX_BADGE_UPLOAD_SIDE_PX = 1024
# The point values RAWeb accepts (`AchievementPoints`), the ones RAIntegration offers.
ACHIEVEMENT_POINT_VALUES = frozenset({0, 1, 2, 3, 4, 5, 10, 25, 50, 100})
# The achievement fields an `AchievementRevision` records.
REVISED_FIELDS = ("title", "description", "points", "type", "mem_addr", "badge_name", "status")


def badge_name_for(number):
    return f"{number:0{BADGE_NAME_DIGITS}d}"


def validate_badge_image(file):
    """Accepts a PNG, JPEG or GIF of at most `MAX_BADGE_UPLOAD_BYTES` and
    `MAX_BADGE_UPLOAD_SIDE_PX` a side, judged by its contents rather than its name."""
    if file.size > MAX_BADGE_UPLOAD_BYTES:
        raise ValidationError(
            _("The badge image must be at most %(limit)s bytes."),
            code="file_too_large",
            params={"limit": MAX_BADGE_UPLOAD_BYTES},
        )
    try:
        file.seek(0)
        with Image.open(file) as image:
            image_format = image.format
            width, height = image.size
            image.verify()
    except (OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValidationError(
            _("Upload a PNG, JPEG or GIF image."), code="invalid_image"
        ) from error
    finally:
        file.seek(0)
    if image_format not in BADGE_UPLOAD_FORMATS:
        raise ValidationError(_("Upload a PNG, JPEG or GIF image."), code="invalid_image")
    elif max(width, height) > MAX_BADGE_UPLOAD_SIDE_PX:
        raise ValidationError(
            _("The badge image must be at most %(limit)s pixels on each side."),
            code="image_too_large",
            params={"limit": MAX_BADGE_UPLOAD_SIDE_PX},
        )
    else:
        _validate_badge_pixels(file)


def _validate_badge_pixels(file):
    """Decodes the image: verify() checks only PNG chunks, so a truncated JPEG or GIF passes it
    and then fails on every render."""
    try:
        with Image.open(file) as image:
            image.load()
    except (OSError, SyntaxError) as error:
        raise ValidationError(
            _("Upload a PNG, JPEG or GIF image."), code="invalid_image"
        ) from error
    finally:
        file.seek(0)


class BadgeQuerySet(models.QuerySet):
    def named(self, name):
        """The badge called `name`, else `None`; only the canonical zero-padded name matches."""
        if BADGE_NAME_PATTERN.fullmatch(name) is None:
            return None
        number = int(name)
        if badge_name_for(number) != name:
            return None
        else:
            return self.filter(pk=number).first()


class Badge(models.Model):
    """An uploaded badge image, named after its sequential number as RA names badges.

    The image never changes once uploaded: new art is a new badge, so a name always shows the
    same picture and clients may cache it by name.
    """

    image = models.ImageField(
        upload_to="badges/", validators=[validate_badge_image], verbose_name=_("image")
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("uploaded by"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("created at"))

    objects = BadgeQuerySet.as_manager()

    class Meta:
        verbose_name = _("badge")
        verbose_name_plural = _("badges")
        ordering = ["id"]

    def __str__(self):
        return self.name

    @property
    def name(self):
        return badge_name_for(self.pk)


def is_known_badge_name(name):
    return name == PLACEHOLDER_BADGE_NAME or Badge.objects.named(name) is not None


class Achievement(models.Model):
    # Both reach every player and client; only an official achievement is awarded and worth
    # points.
    STATUS_OFFICIAL = "official"
    STATUS_UNOFFICIAL = "unofficial"
    STATUS_CHOICES = [
        (STATUS_OFFICIAL, _("Official")),
        (STATUS_UNOFFICIAL, _("Unofficial")),
    ]
    # Read by the Crash seed helpers in `management/crash1.py`; remove once they name
    # STATUS_OFFICIAL.
    STATUS_COMMUNITY = STATUS_OFFICIAL

    # The rcheevos achievement types, sent verbatim as `Type`; "" is a standard achievement.
    TYPE_NONE = ""
    TYPE_PROGRESSION = "progression"
    TYPE_WIN_CONDITION = "win_condition"
    TYPE_MISSABLE = "missable"
    TYPE_CHOICES = [
        (TYPE_NONE, _("None")),
        (TYPE_PROGRESSION, _("Progression")),
        (TYPE_WIN_CONDITION, _("Win condition")),
        (TYPE_MISSABLE, _("Missable")),
    ]

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
    badge_name = models.CharField(
        max_length=BADGE_NAME_MAX_CHARS,
        default=PLACEHOLDER_BADGE_NAME,
        verbose_name=_("badge name"),
        help_text=_("The number of an uploaded badge, or 00000 for the placeholder."),
    )
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_UNOFFICIAL,
        verbose_name=_("status"),
    )
    type = models.CharField(
        max_length=16,
        choices=TYPE_CHOICES,
        default=TYPE_NONE,
        blank=True,
        verbose_name=_("type"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("created at"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("updated at"))

    class Meta:
        verbose_name = _("achievement")
        verbose_name_plural = _("achievements")
        ordering = ["game", "title"]

    def __str__(self):
        return f"{self.title} ({self.game})"

    def clean(self):
        super().clean()
        if not is_known_badge_name(self.badge_name):
            raise ValidationError(
                {"badge_name": _("No badge has this name; upload the badge first.")}
            )

    def save(self, *args, editor=None, **kwargs):
        """Saves the achievement and records a revision when a revised field changed; `editor` is
        who changed it, `None` when unknown."""
        with transaction.atomic():
            if not self._state.adding:
                record_baselines([self.pk])
            else:
                # A new achievement has no stored state to record.
                pass
            super().save(*args, **kwargs)
            record_revisions([self.pk], editor)

    def revised_values(self):
        return {field: getattr(self, field) for field in REVISED_FIELDS}


class AchievementRevision(models.Model):
    """An achievement's revised fields as one change left them. History is append-only: a revert
    is a new revision."""

    achievement = models.ForeignKey(
        Achievement,
        on_delete=models.CASCADE,
        related_name="revisions",
        verbose_name=_("achievement"),
    )
    # `None` when unknown: a baseline, or a save that named no editor.
    editor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("editor"),
    )
    title = models.CharField(
        max_length=Achievement._meta.get_field("title").max_length, verbose_name=_("title")
    )
    description = models.TextField(verbose_name=_("description"))
    points = models.IntegerField(verbose_name=_("points"))
    mem_addr = models.TextField(verbose_name=_("memory address expression"))
    badge_name = models.CharField(max_length=BADGE_NAME_MAX_CHARS, verbose_name=_("badge name"))
    status = models.CharField(
        max_length=Achievement._meta.get_field("status").max_length,
        choices=Achievement.STATUS_CHOICES,
        verbose_name=_("status"),
    )
    type = models.CharField(
        max_length=Achievement._meta.get_field("type").max_length,
        choices=Achievement.TYPE_CHOICES,
        blank=True,
        verbose_name=_("type"),
    )
    created_at = models.DateTimeField(
        default=timezone.now, editable=False, verbose_name=_("created at")
    )

    class Meta:
        verbose_name = _("achievement revision")
        verbose_name_plural = _("achievement revisions")
        ordering = ["achievement", "created_at", "pk"]

    def __str__(self):
        return f"{self.achievement} @ {self.created_at:%Y-%m-%d %H:%M:%S}"

    def revised_values(self):
        return {field: getattr(self, field) for field in REVISED_FIELDS}


def _latest_revised_values(achievement_ids):
    """`{achievement_id: revised values}` of each achievement's latest revision."""
    latest = (
        AchievementRevision.objects.filter(achievement_id__in=achievement_ids)
        .order_by("achievement_id", "-created_at", "-pk")
        .distinct("achievement_id")
        .values("achievement_id", *REVISED_FIELDS)
    )
    return {row.pop("achievement_id"): row for row in latest}


def _subset_title(set_type, set_title):
    """A core game may keep a `set_title` from when it was a subset; only a subset's counts."""
    if set_type is None:
        return ""
    else:
        return set_title


def record_revisions(achievement_ids, editor):
    """Records, by `editor`, the stored state of each achievement whose revised fields differ from
    its latest revision, so a save that changed none of them records nothing, and notifies each
    author whose achievement's status changed: every status change is recorded here."""
    latest = _latest_revised_values(achievement_ids)
    stored = Achievement.objects.filter(pk__in=achievement_ids).values(
        "pk",
        "game_id",
        "game__set_type",
        "game__set_title",
        "author_id",
        "author__is_active",
        *REVISED_FIELDS,
    )
    revisions = []
    status_changes = []
    for row in stored:
        values = {field: row[field] for field in REVISED_FIELDS}
        previous = latest.get(row["pk"])
        if previous is None:
            # A new achievement: its first revision, no status change.
            revisions.append(AchievementRevision(achievement_id=row["pk"], editor=editor, **values))
        elif previous == values:
            # Nothing revised changed since the latest revision.
            pass
        else:
            revisions.append(AchievementRevision(achievement_id=row["pk"], editor=editor, **values))
            if previous["status"] != values["status"]:
                status_changes.append(
                    StatusChange(
                        achievement_id=row["pk"],
                        game_id=row["game_id"],
                        author_id=row["author_id"],
                        author_is_active=row["author__is_active"],
                        title=values["title"],
                        old_status=previous["status"],
                        new_status=values["status"],
                        set_title=_subset_title(row["game__set_type"], row["game__set_title"]),
                    )
                )
            else:
                # Another revised field changed; the status stayed.
                pass
    AchievementRevision.objects.bulk_create(revisions)
    notify_status_changes(status_changes, editor)


def record_baselines(achievement_ids):
    """Records the stored state of each achievement that has no revision yet, dated when it was
    last updated, so its first recorded change has a state to differ from.

    Covers achievements written without `save()`: `bulk_create`, `update()` and `loaddata`.
    Must run in a transaction.
    """
    # Locked first, so two concurrent first changes cannot both find no revision.
    list(
        Achievement.objects.select_for_update()
        .filter(pk__in=achievement_ids)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    # TRADEOFF: such a write to an achievement that already has revisions is folded into its next
    # revision, by that editor; compare with the latest revision if a path starts doing that.
    stored = Achievement.objects.filter(pk__in=achievement_ids, revisions__isnull=True).values(
        "pk", "updated_at", *REVISED_FIELDS
    )
    AchievementRevision.objects.bulk_create(
        [
            AchievementRevision(
                achievement_id=row.pop("pk"), created_at=row.pop("updated_at"), **row
            )
            for row in stored
        ]
    )


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
    unlocked_at = models.DateTimeField(
        default=timezone.now, editable=False, verbose_name=_("unlocked at")
    )

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
    # Who last changed the text; `None` while it is the text its author created it with.
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("updated by"),
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("updated at"))

    class Meta:
        verbose_name = _("code note")
        verbose_name_plural = _("code notes")
        ordering = ["game", "address"]

    def __str__(self):
        return f"{self.address} ({self.game})"

    def clean(self):
        super().clean()
        if self.game_id is not None and self.game.is_subset:
            raise ValidationError(
                {"game": _("A subset shares its parent game's code notes: note the parent game.")}
            )
        else:
            pass

    @property
    def last_writer(self):
        """Who wrote the current text, whom RAIntegration credits the note to."""
        return self.updated_by or self.author
