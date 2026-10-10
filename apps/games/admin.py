from django import forms
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.games.models import Console, Game, GameHash, PlayerGame, UserSetPreference
from apps.images.catalog import versioned_game_icon_path
from apps.images.rendering import ADMIN_LIST_THUMBNAIL_PX, GAME_ICON_SIZE_PX


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


class SubsetForm(forms.ModelForm):
    """A subset of the game being edited, on its parent's console."""

    class Meta:
        model = Game
        fields = ("set_type", "set_title", "title", "icon", "rich_presence_patch")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A subset row always has a type; the model's blank choice is for core games.
        self.fields["set_type"].required = True

    def clean(self):
        cleaned_data = super().clean()
        # The inline formset's parent, which may not be saved yet.
        parent = cleaned_data.get("parent_game")
        if parent is not None:
            self.instance.console_id = parent.console_id
        else:
            # Without a parent the model's clean reports the subset as orphaned.
            pass
        return cleaned_data


class SubsetInline(admin.StackedInline):
    model = Game
    form = SubsetForm
    fk_name = "parent_game"
    extra = 0
    show_change_link = True
    verbose_name = _("subset")
    verbose_name_plural = _("subsets")


@admin.register(Console)
class ConsoleAdmin(admin.ModelAdmin):
    list_display = ("ra_id", "name", "short_name")
    search_fields = ("name", "short_name")
    ordering = ("ra_id",)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("icon_thumbnail", "title", "console", "set_type", "parent_game", "created_at")
    list_display_links = ("icon_thumbnail", "title")
    list_filter = ("console", "set_type")
    list_select_related = ("console", "parent_game")
    search_fields = ("title",)
    readonly_fields = ("icon_preview",)
    autocomplete_fields = ("parent_game",)

    def get_inlines(self, request, obj):
        """Subsets hang off core games only."""
        if obj is not None and obj.is_subset:
            return [GameHashInline]
        else:
            return [GameHashInline, SubsetInline]

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


@admin.register(PlayerGame)
class PlayerGameAdmin(admin.ModelAdmin):
    """View only: the emulator's session requests write these rows, and rarity counts them as
    players, so deleting one would leave its unlockers uncounted."""

    list_display = (
        "user",
        "game",
        "hardcore",
        "playtime_seconds",
        "first_played_at",
        "last_played_at",
        "last_ping_at",
    )
    list_filter = ("hardcore", "game__console")
    search_fields = ("user__username", "game__title", "last_rich_presence")
    list_select_related = ("user", "game")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserSetPreference)
class UserSetPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "subset_game", "opted_in")
    list_filter = ("opted_in", "subset_game__set_type")
    search_fields = ("user__username", "subset_game__title", "subset_game__set_title")
    list_select_related = ("user", "subset_game")
    autocomplete_fields = ("user",)
