from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AnticheatConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.anticheat"
    verbose_name = _("Anti-cheat")
