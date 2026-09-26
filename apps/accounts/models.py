from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

API_TOKEN_BYTES = 32
HEX_DIGITS_PER_BYTE = 2


class User(AbstractUser):
    api_token = models.CharField(
        max_length=API_TOKEN_BYTES * HEX_DIGITS_PER_BYTE, unique=True, null=True, blank=True
    )
    api_token_expires_at = models.DateTimeField(null=True, blank=True)
    softcore_points = models.IntegerField(default=0)
    hardcore_points = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

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
