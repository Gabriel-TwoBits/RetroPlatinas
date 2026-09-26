from django.contrib import admin
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from apps.anticheat.models import SuspiciousActivity


@admin.register(SuspiciousActivity)
class SuspiciousActivityAdmin(admin.ModelAdmin):
    """Review only: the API records these rows, and a reviewer sets the verdict with the bulk
    actions."""

    list_display = (
        "created_at",
        "user",
        "kind",
        "review_status",
        "reviewed_by",
        "reviewed_at",
        "detail",
    )
    list_filter = ("review_status", "kind", "created_at")
    search_fields = ("user__username",)
    list_select_related = ("user", "reviewed_by")
    date_hierarchy = "created_at"
    readonly_fields = (
        "user",
        "kind",
        "detail",
        "created_at",
        "review_status",
        "reviewed_by",
        "reviewed_at",
    )
    actions = ("mark_legit", "mark_cheater")

    def has_add_permission(self, request):
        return False

    @admin.action(description=_("Mark selected activities as legitimate"), permissions=("change",))
    def mark_legit(self, request, queryset):
        self._review(request, queryset, SuspiciousActivity.ReviewStatus.LEGIT)

    @admin.action(description=_("Mark selected activities as cheating"), permissions=("change",))
    def mark_cheater(self, request, queryset):
        self._review(request, queryset, SuspiciousActivity.ReviewStatus.CHEATER)

    def _review(self, request, queryset, status):
        reviewed = queryset.update(
            review_status=status, reviewed_by=request.user, reviewed_at=timezone.now()
        )
        message = ngettext(
            "%(count)d activity reviewed as “%(status)s”.",
            "%(count)d activities reviewed as “%(status)s”.",
            reviewed,
        ) % {"count": reviewed, "status": status.label}
        self.message_user(request, message)
