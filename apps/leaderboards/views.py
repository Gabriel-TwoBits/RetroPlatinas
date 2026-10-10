from django.core.paginator import InvalidPage
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe

from apps.leaderboards import page
from apps.leaderboards.models import Leaderboard


@require_safe
def leaderboard_detail(request, game_id, leaderboard_id):
    # A leaderboard of another game is unknown under this one.
    leaderboard = get_object_or_404(
        Leaderboard.objects.select_related("game__console", "game__parent_game"),
        pk=leaderboard_id,
        game_id=game_id,
    )
    try:
        context = page.board_context(leaderboard, request.user, request.GET.get("page", 1))
    except InvalidPage as error:
        raise Http404("Unknown leaderboard page") from error
    return render(request, "leaderboards/detail.html", context)
