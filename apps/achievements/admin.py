from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from apps.achievements.models import Achievement, CodeNote, UserUnlock
from apps.images.catalog import badge_path
from apps.images.rendering import ADMIN_LIST_THUMBNAIL_PX, BADGE_SIZE_PX

_STATUS_COLORS = {
    Achievement.STATUS_DRAFT: "#888888",
    Achievement.STATUS_COMMUNITY: "#d97706",
    Achievement.STATUS_VERIFIED: "#16a34a",
}


def _badge_img(achievement, locked, size):
    alt = _("Locked badge") if locked else _("Badge")
    return format_html(
        '<img src="{}" alt="{}" width="{}" height="{}">',
        badge_path(achievement, locked=locked),
        alt,
        size,
        size,
    )


def _published_unlock_points(hardcore):
    points = (
        UserUnlock.objects.filter(
            user=OuterRef("pk"),
            hardcore=hardcore,
            achievement__status__in=Achievement.PUBLISHED_STATUSES,
        )
        .values("user")
        .annotate(total=Sum("achievement__points"))
        .values("total")
    )
    return Coalesce(Subquery(points), 0)


def _recalculate_unlocker_points(achievement_ids):
    """Recompute the point totals of everyone who unlocked these achievements from their unlocks.

    Only published unlocks count; unlocks are kept, so a draft counts again once republished.
    """
    unlockers = get_user_model().objects.filter(
        pk__in=UserUnlock.objects.filter(achievement_id__in=achievement_ids).values("user_id")
    )
    # handle_awardachievement increments under this row lock, so a concurrent award is not lost.
    list(unlockers.select_for_update().values_list("pk", flat=True))
    unlockers.update(
        softcore_points=_published_unlock_points(hardcore=False),
        hardcore_points=_published_unlock_points(hardcore=True),
    )


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = (
        "badge_thumbnail",
        "title",
        "game",
        "colored_status",
        "type",
        "points",
        "author",
        "created_at",
    )
    list_display_links = ("badge_thumbnail", "title")
    readonly_fields = ("badge_preview",)
    list_filter = ("status", "type", "game__console")
    search_fields = ("title", "description", "mem_addr")
    autocomplete_fields = ("author", "game")
    actions = ("publish_as_community", "mark_verified", "move_to_draft")

    @admin.display(description=_("status"))
    def colored_status(self, obj):
        color = _STATUS_COLORS.get(obj.status, "#000000")
        label = obj.get_status_display()
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, label)

    @admin.display(description=_("badge"))
    def badge_thumbnail(self, obj):
        return _badge_img(obj, locked=False, size=ADMIN_LIST_THUMBNAIL_PX)

    @admin.display(description=_("badge preview"))
    def badge_preview(self, obj):
        """The unlocked and locked badges as clients receive them, placeholder included."""
        if obj.pk is None:
            return _("Available after saving.")
        else:
            return format_html(
                "{} {}",
                _badge_img(obj, locked=False, size=BADGE_SIZE_PX),
                _badge_img(obj, locked=True, size=BADGE_SIZE_PX),
            )

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

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if "status" in form.changed_data:
            _recalculate_unlocker_points([obj.pk])

    def _change_status(self, request, queryset, status):
        with transaction.atomic():
            changing_ids = list(queryset.exclude(status=status).values_list("pk", flat=True))
            changed = Achievement.objects.filter(pk__in=changing_ids).update(
                status=status, updated_at=timezone.now()
            )
            _recalculate_unlocker_points(changing_ids)
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
