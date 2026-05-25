from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.achievements.models import Achievement, CodeNote, UserUnlock

_STATUS_COLORS = {
    Achievement.STATUS_DRAFT: "#888888",
    Achievement.STATUS_COMMUNITY: "#d97706",
    Achievement.STATUS_VERIFIED: "#16a34a",
}


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ("title", "game", "colored_status", "points", "flags", "author", "created_at")
    list_filter = ("status", "game__console")
    search_fields = ("title", "description", "mem_addr")
    raw_id_fields = ("author", "game")

    @admin.display(description=_("status"))
    def colored_status(self, obj):
        color = _STATUS_COLORS.get(obj.status, "#000000")
        label = obj.get_status_display()
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, label)


@admin.register(UserUnlock)
class UserUnlockAdmin(admin.ModelAdmin):
    list_display = ("user", "achievement", "hardcore", "unlocked_at")
    list_filter = ("hardcore",)
    search_fields = ("user__username", "achievement__title")
    raw_id_fields = ("user", "achievement")


@admin.register(CodeNote)
class CodeNoteAdmin(admin.ModelAdmin):
    list_display = ("game", "address", "author", "updated_at")
    list_filter = ("game",)
    search_fields = ("address", "note")
    raw_id_fields = ("author", "game")
