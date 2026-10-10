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
# rc_client pings every 120 s while a game is loaded (`rc_client_ping` in rc_client.c).
RC_CLIENT_PING_INTERVAL = timedelta(seconds=120)
# Pings that may go missing while play still counts as continuous.
LOST_PINGS_TOLERATED = 1
PLAYTIME_MAX_PING_GAP = RC_CLIENT_PING_INTERVAL * (LOST_PINGS_TOLERATED + 1)
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


# RA's subset types; a core set has none.
SET_TYPE_BONUS = "bonus"
SET_TYPE_CHALLENGE = "challenge"
SET_TYPE_SPECIALTY = "specialty"
SET_TYPE_EXCLUSIVE = "exclusive"
SET_TYPE_CHOICES = [
    (SET_TYPE_BONUS, _("Bonus")),
    (SET_TYPE_CHALLENGE, _("Challenge")),
    (SET_TYPE_SPECIALTY, _("Specialty")),
    (SET_TYPE_EXCLUSIVE, _("Exclusive")),
]
SUBSET_TYPES = [value for value, _label in SET_TYPE_CHOICES]
# Played alongside the core set once the player opts in; these have no disc hash of their own.
OPT_IN_SET_TYPES = [SET_TYPE_BONUS, SET_TYPE_CHALLENGE]


class GameQuerySet(models.QuerySet):
    def core(self):
        """The games that are not a subset of another."""
        return self.filter(set_type__isnull=True)


class Game(models.Model):
    """A game's core set, or, with a parent and a `set_type`, one of its subsets (RA's
    "supporting game"): achievements, leaderboards, players and rarity are per row."""

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
    parent_game = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subsets",
        limit_choices_to={"set_type__isnull": True},
        verbose_name=_("parent game"),
    )
    set_type = models.CharField(
        max_length=16,
        choices=SET_TYPE_CHOICES,
        null=True,
        blank=True,
        verbose_name=_("subset type"),
        help_text=_("Empty for a game's core set."),
    )
    set_title = models.CharField(
        max_length=128,
        blank=True,
        verbose_name=_("subset title"),
        help_text=_('The name the emulator shows for the subset, such as "Bonus".'),
    )

    objects = GameQuerySet.as_manager()

    class Meta:
        verbose_name = _("game")
        verbose_name_plural = _("games")
        ordering = ["title"]
        constraints = [
            models.CheckConstraint(
                # `set_type IN (...)` is NULL, which a CHECK passes, for a NULL type.
                condition=models.Q(set_type__isnull=True, parent_game__isnull=True)
                | (
                    models.Q(
                        set_type__isnull=False,
                        set_type__in=SUBSET_TYPES,
                        parent_game__isnull=False,
                    )
                    & ~models.Q(set_title="")
                ),
                name="games_game_core_or_titled_subset",
            ),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # A subset is on its parent's console (`clean`), so a core game's subsets follow it.
        if self.is_subset:
            # A subset has no subsets of its own (`clean`).
            pass
        else:
            self.subsets.exclude(console_id=self.console_id).update(console_id=self.console_id)

    @property
    def is_subset(self):
        return self.set_type is not None

    @property
    def core_game(self):
        """The core game this set belongs to: its parent for a subset, else itself."""
        if self.is_subset:
            return self.parent_game
        else:
            return self

    def clean(self):
        super().clean()
        # The related object, not its id: an admin inline sets a parent not saved yet.
        parent = self.parent_game
        if self.set_type is None and parent is None:
            return
        elif self.set_type is None:
            raise ValidationError(
                {"set_type": _("A game with a parent game is a subset: choose its type.")}
            )
        elif parent is None:
            raise ValidationError({"parent_game": _("A subset needs a parent game.")})
        else:
            self._clean_subset(parent)

    def _clean_subset(self, parent):
        errors = {}
        if self.pk is not None and parent.pk == self.pk:
            errors["parent_game"] = _("A game cannot be its own parent.")
        elif parent.is_subset:
            errors["parent_game"] = _("The parent game must be a core game, not a subset.")
        elif self.console_id != parent.console_id:
            errors["console"] = _("A subset is on its parent game's console.")
        else:
            pass
        if self.pk is not None and Game.objects.filter(parent_game_id=self.pk).exists():
            errors["set_type"] = _("This game has subsets of its own, so it cannot be a subset.")
        elif (
            self.pk is not None
            and self.set_type in OPT_IN_SET_TYPES
            and GameHash.objects.filter(game_id=self.pk).exists()
        ):
            errors["set_type"] = _(
                "A bonus or challenge subset loads with its parent game's discs: move this "
                "game's hashes to the parent game first."
            )
        else:
            pass
        if not self.set_title:
            errors["set_title"] = _("A subset needs a title.")
        if errors:
            raise ValidationError(errors)


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
        elif self._game_or_none() is not None and self.game.set_type in OPT_IN_SET_TYPES:
            raise ValidationError(
                _(
                    "A bonus or challenge subset loads with its parent game's discs: link the "
                    "hash to the parent game."
                )
            )
        else:
            pass

    def _game_or_none(self):
        """The game, else `None`; an admin inline on a game not saved yet sets it unsaved."""
        if self.game_id is not None or GameHash.game.is_cached(self):
            return self.game
        else:
            return None

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
    session_started_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("session started at")
    )
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

    def start_session(self, now):
        """Marks a new session live at `now`.

        The gap since the previous session was not play, so it credits nothing, and the
        previous session's rich presence is cleared until this one's first ping.
        """
        self.last_played_at = now
        self.last_rich_presence = ""
        self.last_ping_at = now
        self.session_started_at = now

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


class UserSetPreference(models.Model):
    """A player's choice to play a bonus or challenge subset; without one the subset is off."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="set_preferences",
        verbose_name=_("user"),
    )
    subset_game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        related_name="set_preferences",
        limit_choices_to={"set_type__in": OPT_IN_SET_TYPES},
        verbose_name=_("subset"),
    )
    opted_in = models.BooleanField(default=False, verbose_name=_("opted in"))

    class Meta:
        verbose_name = _("subset preference")
        verbose_name_plural = _("subset preferences")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "subset_game"], name="games_usersetpreference_user_subset_unique"
            ),
        ]

    def __str__(self):
        return f"{self.user} — {self.subset_game}"
