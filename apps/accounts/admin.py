from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "username",
        "email",
        "softcore_points",
        "hardcore_points",
        "is_staff",
        "date_joined",
    )
    fieldsets = DjangoUserAdmin.fieldsets + (
        (
            "RetroCheevos",
            {"fields": ("softcore_points", "hardcore_points", "api_token", "api_token_expires_at")},
        ),
    )
