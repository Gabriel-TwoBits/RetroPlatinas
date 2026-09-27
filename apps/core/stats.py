"""Rankings, point totals and completion, shared by the API and the site pages."""


def rank_by_score(entries, lower_is_better, score):
    """Competition rank ("1224") of `score` among the leaderboard `entries`: one more than the
    number of strictly better scores."""
    better = "score__lt" if lower_is_better else "score__gt"
    return entries.filter(**{better: score}).count() + 1


def ranked_entries(entries, lower_is_better, offset, count):
    """`(index, rank, entry)` for `count` of the leaderboard `entries` after the first `offset`,
    best first.

    `index` is the 1-based position on the board; tied scores share the competition rank
    `rank_by_score` gives them.
    """
    order = "score" if lower_is_better else "-score"
    board = entries.select_related("user").order_by(order, "submitted_at", "id")
    ranked = []
    previous_score = None
    previous_rank = None
    for index, entry in enumerate(board[offset : offset + count], start=offset + 1):
        if previous_rank is None:
            rank = rank_by_score(entries, lower_is_better, entry.score)
        elif entry.score == previous_score:
            rank = previous_rank
        else:
            rank = index
        ranked.append((index, rank, entry))
        previous_score = entry.score
        previous_rank = rank
    return ranked
