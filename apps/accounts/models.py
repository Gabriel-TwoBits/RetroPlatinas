from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

API_TOKEN_BYTES = 32
HEX_DIGITS_PER_BYTE = 2
API_TOKEN_HEX_LENGTH = API_TOKEN_BYTES * HEX_DIGITS_PER_BYTE
BIO_MAX_LENGTH = 100


class User(AbstractUser):
    api_token = models.CharField(
        max_length=API_TOKEN_HEX_LENGTH, unique=True, null=True, blank=True
    )
    api_token_expires_at = models.DateTimeField(null=True, blank=True)
    softcore_points = models.IntegerField(default=0)
    hardcore_points = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    bio = models.CharField(max_length=BIO_MAX_LENGTH, blank=True, verbose_name=_("bio"))

    class Meta(AbstractUser.Meta):
        constraints = [
            # System accounts (e.g. `ra-import`) have no email, so "" is exempt.
            models.UniqueConstraint(
                Lower("email"),
                condition=~models.Q(email=""),
                name="accounts_user_email_ci_unique",
                violation_error_message=_("A user with that email already exists."),
            ),
        ]


class Friendship(models.Model):
    """A one-way follow: `user` follows `friend`."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="follows", verbose_name=_("user")
    )
    friend = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="followed_by", verbose_name=_("friend")
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("created at"))

    class Meta:
        verbose_name = _("friendship")
        verbose_name_plural = _("friendships")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "friend"], name="accounts_friendship_user_friend_unique"
            ),
            models.CheckConstraint(
                condition=~models.Q(user=models.F("friend")),
                name="accounts_friendship_no_self_follow",
            ),
        ]

    def __str__(self):
        return f"{self.user} → {self.friend}"
