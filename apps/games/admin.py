from django import forms
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.games.models import Console, Game, GameHash
from apps.images.catalog import versioned_game_icon_path
from apps.images.rendering import GAME_ICON_SIZE_PX

ADMIN_LIST_THUMBNAIL_PX = 32


def _icon_img(game, size):
    return format_html(
        '<img src="{}" alt="{}" width="{}" height="{}">',
        versioned_game_icon_path(game),
        _("Game icon"),
        size,
        size,
    )


class GameHashForm(forms.ModelForm):
    """Lowercases md5 in cleaned_data, where the inline formset's duplicate check reads it."""

    class Meta:
        model = GameHash
        fields = "__all__"

    def clean_md5(self):
        return self.cleaned_data["md5"].lower()


class GameHashInline(admin.TabularInline):
    model = GameHash
    form = GameHashForm
    extra = 1


@admin.register(Console)
class ConsoleAdmin(admin.ModelAdmin):
    list_display = ("ra_id", "name", "short_name")
    search_fields = ("name", "short_name")
    ordering = ("ra_id",)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("icon_thumbnail", "title", "console", "created_at")
    list_display_links = ("icon_thumbnail", "title")
    list_filter = ("console",)
    search_fields = ("title",)
    readonly_fields = ("icon_preview",)
    inlines = [GameHashInline]

    @admin.display(description=_("icon"))
    def icon_thumbnail(self, obj):
        return _icon_img(obj, ADMIN_LIST_THUMBNAIL_PX)

    @admin.display(description=_("icon preview"))
    def icon_preview(self, obj):
        """The icon as clients receive it, placeholder included."""
        if obj.pk is None:
            return _("Available after saving.")
        else:
            return _icon_img(obj, GAME_ICON_SIZE_PX)


@admin.register(GameHash)
class GameHashAdmin(admin.ModelAdmin):
    form = GameHashForm
    list_display = ("md5", "game", "label")
    search_fields = ("md5", "label")
    list_filter = ("game__console",)
