from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe

from apps.games import page
from apps.games.models import Game


def _game(game_id):
    return get_object_or_404(Game.objects.select_related("console"), pk=game_id)


@require_safe
def game_detail(request, game_id):
    game = _game(game_id)
    return render(request, "games/detail.html", page.game_context(game, request.user))


@require_safe
def game_panel(request, game_id, tab):
    if tab not in page.VALID_TABS:
        raise Http404("Unknown game tab")
    achievement_filter = request.GET.get("filter", page.FILTER_ALL)
    if achievement_filter not in page.VALID_FILTERS:
        return HttpResponseBadRequest("Unknown achievement filter")
    else:
        game = _game(game_id)
        context = page.panel_context(game, request.user, tab, achievement_filter)
        return render(request, "games/partials/tabs.html", context)
