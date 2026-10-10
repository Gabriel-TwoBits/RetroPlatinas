from http import HTTPStatus

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import InvalidPage
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from apps.core import htmx
from apps.games import listing, page
from apps.games.forms import GameFilterForm, NewSubsetForm
from apps.games.models import OPT_IN_SET_TYPES, SUBSET_TYPES, Game, UserSetPreference

PAGE_PARAM = "page"
# The opt-in control posts `play`: whether the player plays the subset from the next load on.
PLAY_PARAM = "play"
PLAY_VALUES = {"on": True, "off": False}


def _game(game_id):
    return get_object_or_404(Game.objects.select_related("console"), pk=game_id)


def _core_game(game_id):
    """The core game `game_id`; a subset has no page of its own."""
    return get_object_or_404(Game.objects.core().select_related("console"), pk=game_id)


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
    if game.is_subset:
        return redirect(game.get_absolute_url())
    else:
        return render(request, "games/detail.html", page.game_context(game, request.user))


@require_safe
def game_panel(request, game_id, tab):
    game = _core_game(game_id)
    achievement_filter = request.GET.get("filter", page.FILTER_ALL)
    if tab not in page.VALID_TABS:
        raise Http404("Unknown game tab")
    elif achievement_filter not in page.VALID_FILTERS:
        return HttpResponseBadRequest(gettext("Unknown achievement filter"))
    else:
        context = page.panel_context(game, request.user, tab, achievement_filter)
        return render(request, "games/partials/tabs.html", context)


@require_POST
def subset_opt_in(request, game_id):
    """Turns a bonus or challenge subset on or off for the player; the emulator serves it from
    the next time the game loads."""
    subset = get_object_or_404(
        Game.objects.filter(set_type__in=OPT_IN_SET_TYPES).select_related("parent_game"),
        pk=game_id,
    )
    play = request.POST.get(PLAY_PARAM)
    if not request.user.is_authenticated:
        return htmx.login_redirect(request, f"#{subset.anchor}")
    elif play not in PLAY_VALUES:
        return HttpResponseBadRequest(gettext("Choose whether to play the subset."))
    else:
        UserSetPreference.objects.update_or_create(
            user=request.user, subset_game=subset, defaults={"opted_in": PLAY_VALUES[play]}
        )
        if htmx.is_htmx(request):
            return render(
                request,
                "games/partials/opt-in.html",
                page.opt_in_context(subset, PLAY_VALUES[play]),
            )
        else:
            return redirect(subset.get_absolute_url())


@login_required
@require_http_methods(["GET", "POST"])
def new_subset(request, game_id):
    parent = _core_game(game_id)
    if not request.user.is_staff:
        raise PermissionDenied("Only staff add subsets.")
    elif request.method == "POST":
        form = NewSubsetForm(request.POST, parent=parent)
    else:
        form = NewSubsetForm(parent=parent)

    if form.is_bound and form.is_valid():
        subset = form.save()
        messages.success(request, gettext("Subset added."))
        return redirect(subset.get_absolute_url())
    else:
        return render(
            request,
            "games/subset-new.html",
            {
                "form": form,
                "game": parent,
                "explanations": [page.SET_TYPE_EXPLANATIONS[value] for value in SUBSET_TYPES],
            },
        )
