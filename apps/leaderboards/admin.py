from django.contrib import admin

from apps.leaderboards.models import Leaderboard, LeaderboardEntry


@admin.register(Leaderboard)
class LeaderboardAdmin(admin.ModelAdmin):
    list_display = ("title", "game", "format", "lower_is_better", "author", "updated_at")
    list_filter = ("game__console", "format", "lower_is_better")
    search_fields = ("title", "description", "mem_addr")
    autocomplete_fields = ("game", "author")


@admin.register(LeaderboardEntry)
class LeaderboardEntryAdmin(admin.ModelAdmin):
    list_display = ("leaderboard", "user", "score", "submitted_at")
    list_filter = ("leaderboard__game__console",)
    search_fields = ("leaderboard__title", "user__username")
    autocomplete_fields = ("leaderboard", "user")
