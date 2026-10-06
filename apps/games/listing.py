"""What the games list shows: the games matching its filters, a page at a time."""

from django.core.paginator import Paginator
from django.db.models import Q

from apps.core import stats
from apps.games.forms import (
    DEFAULT_MIN_ACHIEVEMENTS,
    ORDER_ACHIEVEMENTS,
    ORDER_PLAYERS,
    ORDER_TITLE,
)
from apps.images.catalog import versioned_game_icon_path

GAMES_PER_PAGE = 24


def _ordering(order):
    """Ties fall back to the title, then the id, so every page is stable."""
    if order == ORDER_TITLE:
        return ("title", "id")
    elif order == ORDER_ACHIEVEMENTS:
        return ("-published_achievements", "title", "id")
    elif order == ORDER_PLAYERS:
        return ("-played_by", "title", "id")
    else:
        raise ValueError(f"Unknown games ordering: {order}")


def matching_games(filters):
    """The games matching a valid `GameFilterForm`'s cleaned data, in its order."""
    title_match = Q(title__icontains=filters["q"]) if filters["q"] else Q()
    console_match = Q(console=filters["console"]) if filters["console"] is not None else Q()
    return (
        stats.catalog_games()
        .filter(title_match, console_match, published_achievements__gte=filters["min_achievements"])
        .order_by(*_ordering(filters["order"]))
    )


def _is_filtered(filters):
    return (
        bool(filters["q"])
        or filters["console"] is not None
        or filters["min_achievements"] != DEFAULT_MIN_ACHIEVEMENTS
    )


def list_context(filters, page_number, query):
    """One page of the games matching `filters`; raises `InvalidPage` for a page it does not have.

    `query` is the list's query string without the page, carried by the page links.
    """
    page = Paginator(matching_games(filters), GAMES_PER_PAGE).page(page_number)
    return {
        "filters": filters,
        "page": page,
        "cards": [{"game": game, "icon_url": versioned_game_icon_path(game)} for game in page],
        "query": query,
        "filtered": _is_filtered(filters),
    }
