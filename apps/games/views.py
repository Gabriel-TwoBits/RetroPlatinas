from http import HTTPStatus

from django.core.paginator import InvalidPage
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext
from django.views.decorators.http import require_safe

from apps.games import listing, page
from apps.games.forms import GameFilterForm
from apps.games.models import Game

PAGE_PARAM = "page"


def _game(game_id):
    return get_object_or_404(Game.objects.select_related("console"), pk=game_id)


def _games_listing(request, template):
    form = GameFilterForm(request.GET)
    if not form.is_valid():
        return HttpResponseBadRequest(gettext("Invalid games filter"))
    else:
        query = request.GET.copy()
        query.pop(PAGE_PARAM, None)
        try:
            context = listing.list_context(
                form.cleaned_data, request.GET.get(PAGE_PARAM, 1), query.urlencode()
            )
        except InvalidPage as error:
            raise Http404("Unknown games page") from error
        return render(request, template, {**context, "form": form})


@require_safe
def games_list(request):
    return _games_listing(request, "games/list.html")


@require_safe
def games_results(request):
    """The results of the list for its HTMX swaps, with the list's own URL in the address bar.

    Replaced, not pushed: htmx's history snapshot keeps the form's rendered values, not the typed
    ones, so Back would restore results under stale filters.
    """
    response = _games_listing(request, "games/partials/results.html")
    if response.status_code != HTTPStatus.OK:
        # htmx swaps nothing on an error, so the address bar keeps the last list shown.
        return response
    elif request.GET:
        response["HX-Replace-Url"] = f"{reverse('games_list')}?{request.GET.urlencode()}"
    else:
        response["HX-Replace-Url"] = reverse("games_list")
    return response


@require_safe
def game_detail(request, game_id):
    game = _game(game_id)
    return render(request, "games/detail.html", page.game_context(game, request.user))


@require_safe
def game_panel(request, game_id, tab):
    game = _game(game_id)
    achievement_filter = request.GET.get("filter", page.FILTER_ALL)
    if tab not in page.VALID_TABS:
        raise Http404("Unknown game tab")
    elif achievement_filter not in page.VALID_FILTERS:
        return HttpResponseBadRequest(gettext("Unknown achievement filter"))
    else:
        context = page.panel_context(game, request.user, tab, achievement_filter)
        return render(request, "games/partials/tabs.html", context)
