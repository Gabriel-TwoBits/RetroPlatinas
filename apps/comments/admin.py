from django.contrib import admin

from apps.comments.models import Comment


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    """Moderation only: staff delete any comment here."""

    list_display = ("created_at", "author", "game", "achievement", "content")
    search_fields = ("author__username", "content")
    list_select_related = ("author", "game", "achievement__game")
    date_hierarchy = "created_at"
    readonly_fields = ("author", "content", "created_at", "game", "achievement")

    def has_add_permission(self, request):
        return False
