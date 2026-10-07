from django.contrib import admin
from django.db import transaction
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from apps.achievements.models import Achievement, Badge, CodeNote, UserUnlock
from apps.achievements.scoring import recalculate_unlocker_points
from apps.games.models import PlayerGame
from apps.images.catalog import badge_path
from apps.images.rendering import ADMIN_LIST_THUMBNAIL_PX, BADGE_SIZE_PX

_STATUS_COLORS = {
    Achievement.STATUS_DRAFT: "#888888",
    Achievement.STATUS_COMMUNITY: "#d97706",
    Achievement.STATUS_VERIFIED: "#16a34a",
}


def _badge_img(name, locked, size):
    alt = _("Locked badge") if locked else _("Badge")
    return format_html(
        '<img src="{}" alt="{}" width="{}" height="{}">',
        badge_path(name, locked=locked),
        alt,
        size,
        size,
    )


def _record_unlockers_as_players(unlocks):
    """Gives each unlocker a `PlayerGame` row for the unlocked achievement's game.

    Rarity divides unlockers by the game's `PlayerGame` rows, so an unlocker without one would
    push it past 100%.
    """
    PlayerGame.objects.bulk_create(
        [
            PlayerGame(
                user_id=unlock.user_id,
                game_id=unlock.achievement.game_id,
                first_played_at=unlock.unlocked_at,
                last_played_at=unlock.unlocked_at,
            )
            for unlock in unlocks.select_related("achievement")
        ],
        ignore_conflicts=True,
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
        return _badge_img(obj.badge_name, locked=False, size=ADMIN_LIST_THUMBNAIL_PX)

    @admin.display(description=_("badge preview"))
    def badge_preview(self, obj):
        """The unlocked and locked badges as clients receive them, placeholder included."""
        if obj.pk is None:
            return _("Available after saving.")
        else:
            return format_html(
                "{} {}",
                _badge_img(obj.badge_name, locked=False, size=BADGE_SIZE_PX),
                _badge_img(obj.badge_name, locked=True, size=BADGE_SIZE_PX),
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
        if "status" in form.changed_data or "points" in form.changed_data:
            recalculate_unlocker_points([obj.pk])
        if "game" in form.changed_data:
            _record_unlockers_as_players(UserUnlock.objects.filter(achievement=obj))

    def _change_status(self, request, queryset, status):
        with transaction.atomic():
            changing_ids = list(queryset.exclude(status=status).values_list("pk", flat=True))
            changed = Achievement.objects.filter(pk__in=changing_ids).update(
                status=status, updated_at=timezone.now()
            )
            recalculate_unlocker_points(changing_ids)
        message = ngettext(
            "%(count)d achievement moved to %(status)s.",
            "%(count)d achievements moved to %(status)s.",
            changed,
        ) % {"count": changed, "status": dict(Achievement.STATUS_CHOICES)[status]}
        self.message_user(request, message)


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ("badge_thumbnail", "badge_name", "uploaded_by", "created_at")
    list_display_links = ("badge_thumbnail", "badge_name")
    search_fields = ("uploaded_by__username",)

    @admin.display(description=_("badge"))
    def badge_thumbnail(self, obj):
        return _badge_img(obj.name, locked=False, size=ADMIN_LIST_THUMBNAIL_PX)

    @admin.display(description=_("badge name"), ordering="id")
    def badge_name(self, obj):
        return obj.name

    def get_readonly_fields(self, request, obj=None):
        # A name always shows the same image, so an uploaded image is never replaced.
        if obj is None:
            return ()
        else:
            return ("badge_name", "badge_thumbnail", "image", "uploaded_by", "created_at")

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("image",)
        else:
            return self.get_readonly_fields(request, obj)

    def has_delete_permission(self, request, obj=None):
        # Achievements refer to badges by name, with no foreign key to protect them, so only a
        # badge no achievement uses may go, and one at a time.
        if obj is None:
            return False
        elif Achievement.objects.filter(badge_name=obj.name).exists():
            return False
        else:
            return super().has_delete_permission(request, obj)

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        # Nothing serves the file once its badge is gone.
        obj.image.delete(save=False)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(UserUnlock)
class UserUnlockAdmin(admin.ModelAdmin):
    list_display = ("user", "achievement", "hardcore", "unlocked_at")
    list_filter = ("hardcore",)
    search_fields = ("user__username", "achievement__title")
    autocomplete_fields = ("user", "achievement")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        _record_unlockers_as_players(UserUnlock.objects.filter(pk=obj.pk))


@admin.register(CodeNote)
class CodeNoteAdmin(admin.ModelAdmin):
    list_display = ("game", "address", "author", "updated_by", "updated_at")
    list_filter = ("game",)
    search_fields = ("address", "note")
    autocomplete_fields = ("author", "updated_by", "game")
