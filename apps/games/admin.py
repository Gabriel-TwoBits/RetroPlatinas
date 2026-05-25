from django.contrib import admin

from apps.games.models import Console, Game, GameHash


class GameHashInline(admin.TabularInline):
    model = GameHash
    extra = 1


@admin.register(Console)
class ConsoleAdmin(admin.ModelAdmin):
    list_display = ("ra_id", "name", "short_name")
    search_fields = ("name", "short_name")
    ordering = ("ra_id",)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("title", "console", "created_at")
    list_filter = ("console",)
    search_fields = ("title",)
    inlines = [GameHashInline]


@admin.register(GameHash)
class GameHashAdmin(admin.ModelAdmin):
    list_display = ("md5", "game", "label")
    search_fields = ("md5", "label")
    list_filter = ("game__console",)
