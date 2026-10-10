from http import HTTPStatus

from django.contrib.auth.decorators import login_required
from django.core.paginator import InvalidPage, Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST, require_safe

from apps.notifications.display import NOTIFICATIONS_PER_PAGE, menu_rows, rows

# htmx stops polling an element whose request answers this status.
HTMX_STOP_POLLING = 286


def _page_number(request):
    try:
        return int(request.GET.get("page", 1))
    except ValueError as error:
        raise Http404("Unknown notifications page") from error


@login_required
@require_safe
def notification_list(request):
    notifications = request.user.notifications.all()
    try:
        page = Paginator(notifications, NOTIFICATIONS_PER_PAGE).page(_page_number(request))
    except InvalidPage as error:
        raise Http404("Unknown notifications page") from error
    return render(
        request,
        "notifications/list.html",
        {
            "page": page,
            "rows": rows(page),
            "has_unread": notifications.unread().exists(),
        },
    )


@require_safe
def unread_count(request):
    """The bell's counter, polled by htmx; once the session is gone, polling stops."""
    if request.user.is_authenticated:
        return render(
            request,
            "notifications/partials/unread-count.html",
            {"unread": request.user.notifications.unread().count()},
        )
    else:
        return HttpResponse(status=HTMX_STOP_POLLING)


@require_safe
def notification_menu(request):
    """The bell's menu, fetched by htmx when it opens; once the session is gone, the page reloads
    to show it."""
    if request.user.is_authenticated:
        return render(
            request, "notifications/partials/menu.html", {"rows": menu_rows(request.user)}
        )
    else:
        response = HttpResponse(status=HTTPStatus.UNAUTHORIZED)
        response["HX-Refresh"] = "true"
        return response


@login_required
@require_POST
def read_notification(request, notification_id):
    """Marks one of the user's notifications read and opens what it is about."""
    notification = get_object_or_404(request.user.notifications, pk=notification_id)
    if not notification.read:
        notification.read = True
        notification.save(update_fields=["read"])
    else:
        # Opening it again changes nothing.
        pass
    if url_has_allowed_host_and_scheme(
        notification.target_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(notification.target_url)
    else:
        return redirect("notification_list")


@login_required
@require_POST
def read_all_notifications(request):
    request.user.notifications.unread().update(read=True)
    return redirect("notification_list")
