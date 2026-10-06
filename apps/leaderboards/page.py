"""What a leaderboard's public page shows: its entries by active users, best first, a page at a
time, and where the viewer stands."""

from django.core.paginator import Paginator

from apps.core import stats
from apps.images.catalog import avatar_path

ENTRIES_PER_PAGE = 100


def _row(index, rank, entry, viewer):
    return {
        "index": index,
        "rank": rank,
        "entry": entry,
        "avatar_url": avatar_path(entry.user.username),
        "is_viewer": entry.user_id == viewer.pk,
    }


def _viewer_entry(entries, viewer):
    if not viewer.is_authenticated:
        return None
    else:
        return entries.select_related("user").filter(user=viewer).first()


def board_context(leaderboard, viewer, page_number):
    """One page of the board; raises `InvalidPage` for a page it does not have.

    The viewer's entry, when it is not on the page, comes apart with its rank on the whole board.
    """
    entries = stats.leaderboard_entries(leaderboard)
    # Paginates board positions; `ranked_entries` fetches the entries at them.
    page = Paginator(range(entries.count()), ENTRIES_PER_PAGE).page(page_number)
    rows = [
        _row(index, rank, entry, viewer)
        for index, rank, entry in stats.ranked_entries(
            entries,
            leaderboard.lower_is_better,
            (page.number - 1) * ENTRIES_PER_PAGE,
            ENTRIES_PER_PAGE,
        )
    ]
    viewer_entry = _viewer_entry(entries, viewer)
    if viewer_entry is None or any(row["is_viewer"] for row in rows):
        viewer_row = None
    else:
        rank = stats.rank_by_score(entries, leaderboard.lower_is_better, viewer_entry.score)
        viewer_row = _row(None, rank, viewer_entry, viewer)
    return {
        "leaderboard": leaderboard,
        "game": leaderboard.game,
        "page": page,
        "rows": rows,
        "viewer_row": viewer_row,
    }
