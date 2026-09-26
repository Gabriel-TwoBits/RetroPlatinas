from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from apps.achievements.models import Achievement, CodeNote, UserUnlock

_STATUS_COLORS = {
    Achievement.STATUS_DRAFT: "#888888",
    Achievement.STATUS_COMMUNITY: "#d97706",
    Achievement.STATUS_VERIFIED: "#16a34a",
}


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ("title", "game", "colored_status", "points", "author", "created_at")
    list_filter = ("status", "game__console")
    search_fields = ("title", "description", "mem_addr")
    autocomplete_fields = ("author", "game")
    actions = ("publish_as_community", "mark_verified", "move_to_draft")

    @admin.display(description=_("status"))
    def colored_status(self, obj):
        color = _STATUS_COLORS.get(obj.status, "#000000")
        label = obj.get_status_display()
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, label)

    @admin.action(
        description=_("Publish selected achievements as community"), permissions=("change",)
    )
    def publish_as_community(self, request, queryset):
        self._change_status(request, queryset, Achievement.STATUS_COMMUNITY)

    @admin.action(description=_("Mark selected achievements as verified"), permissions=("change",))
    def mark_verified(self, request, queryset):
        self._change_status(request, queryset, Achievement.STATUS_VERIFIED)

    @admin.action(
        description=_("Move selected achievements back to draft"), permissions=("change",)
    )
    def move_to_draft(self, request, queryset):
        self._change_status(request, queryset, Achievement.STATUS_DRAFT)

    def _change_status(self, request, queryset, status):
        changed = queryset.exclude(status=status).update(status=status, updated_at=timezone.now())
        message = ngettext(
            "%(count)d achievement moved to %(status)s.",
            "%(count)d achievements moved to %(status)s.",
            changed,
        ) % {"count": changed, "status": dict(Achievement.STATUS_CHOICES)[status]}
        self.message_user(request, message)


@admin.register(UserUnlock)
class UserUnlockAdmin(admin.ModelAdmin):
    list_display = ("user", "achievement", "hardcore", "unlocked_at")
    list_filter = ("hardcore",)
    search_fields = ("user__username", "achievement__title")
    autocomplete_fields = ("user", "achievement")


@admin.register(CodeNote)
class CodeNoteAdmin(admin.ModelAdmin):
    list_display = ("game", "address", "author", "updated_at")
    list_filter = ("game",)
    search_fields = ("address", "note")
    autocomplete_fields = ("author", "game")
