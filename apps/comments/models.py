from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.achievements.models import Achievement
from apps.games.models import Game

# RAWeb's limit for a comment.
COMMENT_MAX_CHARS = 2000


def target_fields(target):
    """The `Comment` fields that point at `target`, a game or an achievement."""
    if isinstance(target, Game):
        return {"game": target}
    elif isinstance(target, Achievement):
        return {"achievement": target}
    else:
        raise TypeError(f"A comment targets a game or an achievement, not {type(target)!r}")


class CommentQuerySet(models.QuerySet):
    def on(self, target):
        return self.filter(**target_fields(target))


class Comment(models.Model):
    """A comment on a game or on an achievement.

    Two foreign keys rather than a GenericForeignKey: the targets are a fixed pair, and real
    foreign keys keep the database's referential integrity, cascading deletes and plain joins.
    """

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name=_("author"),
    )
    content = models.CharField(max_length=COMMENT_MAX_CHARS, verbose_name=_("content"))
    created_at = models.DateTimeField(
        default=timezone.now, editable=False, verbose_name=_("created at")
    )
    game = models.ForeignKey(
        Game,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="comments",
        verbose_name=_("game"),
    )
    achievement = models.ForeignKey(
        Achievement,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="comments",
        verbose_name=_("achievement"),
    )

    objects = CommentQuerySet.as_manager()

    class Meta:
        verbose_name = _("comment")
        verbose_name_plural = _("comments")
        ordering = ["created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(game__isnull=False, achievement__isnull=True)
                    | models.Q(game__isnull=True, achievement__isnull=False)
                ),
                name="comment_has_one_target",
            )
        ]

    def __str__(self):
        return f"{self.author} — {self.target}"

    @property
    def target(self):
        return self.game or self.achievement
