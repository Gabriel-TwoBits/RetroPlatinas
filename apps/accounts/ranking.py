"""What the global ranking page shows: the users holding a rank in one mode, most points first, a
page at a time. The board is the same for every viewer, so it is cached rendered."""

from datetime import timedelta

from django.core.cache import cache
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _

from apps.core import stats
from apps.images.catalog import avatar_path

MODE_HARDCORE = "hardcore"
MODE_SOFTCORE = "softcore"
MODES = [
    (MODE_HARDCORE, _("Hardcore")),
    (MODE_SOFTCORE, _("Softcore")),
]
VALID_MODES = [slug for slug, _label in MODES]

USERS_PER_PAGE = 100
BOARD_CACHE_MINUTES = 5
BOARD_CACHE_SECONDS = int(timedelta(minutes=BOARD_CACHE_MINUTES).total_seconds())


def _row(rank, user, tally, hardcore):
    return {
        "rank": rank,
        "user": user,
        "avatar_url": avatar_path(user.username),
        "points": user.hardcore_points if hardcore else user.softcore_points,
        "unlocked": tally.unlocked,
        "platinums": tally.platinums,
    }


def _board_context(mode, page_number):
    """One page of the mode's ranking; raises `InvalidPage` for a page it does not have."""
    hardcore = mode == MODE_HARDCORE
    # Paginates ranking positions; `ranked_users_page` fetches the users at them.
    page = Paginator(range(stats.ranking(hardcore).count()), USERS_PER_PAGE).page(page_number)
    ranked = stats.ranked_users_page(hardcore, (page.number - 1) * USERS_PER_PAGE, USERS_PER_PAGE)
    tallies = stats.ranking_tallies([user.pk for _index, _rank, user in ranked], hardcore)
    return {
        "modes": MODES,
        "mode": mode,
        "hardcore": hardcore,
        "page": page,
        "rows": [_row(rank, user, tallies[user.pk], hardcore) for _index, rank, user in ranked],
    }


def board_html(mode, page_number):
    """The rendered board for a valid `mode` and an int `page_number`, cached per mode, page and
    language; raises `InvalidPage` for a page the ranking does not have.

    Rendered without the request, so nothing about the viewer can reach the shared copy.
    """
    html = cache.get_or_set(
        f"ranking-board:{mode}:{page_number}:{get_language()}",
        lambda: render_to_string(
            "accounts/partials/ranking-board.html", _board_context(mode, page_number)
        ),
        BOARD_CACHE_SECONDS,
    )
    # The template engine escaped it when rendering.
    return mark_safe(html)
