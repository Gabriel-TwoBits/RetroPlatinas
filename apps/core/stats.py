"""Rankings, point totals, completion and site-wide activity for the stats API, the
`dorequest.php` leaderboard handlers, the profile page, the home page, the game page, the
achievement page, the leaderboard page, the ranking page, the feed page and the games list.

Only official achievements count. Game listings and "games played" hold core games only: a subset
belongs to its parent game. Inactive accounts (system accounts such as `ra-import`,
deactivated users) hold no rank and are left out of player lists and `leaderboard_entries`; the
leaderboard rank helpers rank whichever entries they are given.
"""

from dataclasses import dataclass
from typing import NamedTuple

from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Coalesce

from apps.achievements.models import Achievement, UserUnlock
from apps.games.models import Game, PlayerGame, site_set_order
from apps.leaderboards.models import Leaderboard


class ByMode(NamedTuple):
    """A value per mode. A hardcore unlock also counts as a softcore one, so the softcore value
    covers both modes."""

    hardcore: int | None
    softcore: int | None


def ranked_users():
    return get_user_model().objects.filter(is_active=True)


def official_unlocks():
    return UserUnlock.objects.filter(achievement__status=Achievement.STATUS_OFFICIAL)


def official_achievement_count(game):
    return game.achievements.filter(status=Achievement.STATUS_OFFICIAL).count()


def _global_rank(user, points, users_with_more_points):
    if not user.is_active or points <= 0:
        return None
    else:
        return users_with_more_points + 1


def global_ranks(user):
    """The user's competition rank ("1224") by the points of each mode, `None` in a mode where
    the user has no points or is inactive."""
    with_more_points = ranked_users().aggregate(
        hardcore=Count("pk", filter=Q(hardcore_points__gt=user.hardcore_points)),
        softcore=Count("pk", filter=Q(softcore_points__gt=user.softcore_points)),
    )
    return ByMode(
        hardcore=_global_rank(user, user.hardcore_points, with_more_points["hardcore"]),
        softcore=_global_rank(user, user.softcore_points, with_more_points["softcore"]),
    )


def _points_field(hardcore):
    if hardcore:
        return "hardcore_points"
    else:
        return "softcore_points"


def ranking(hardcore):
    """The users holding a rank in the mode (active, with points in it), most points first."""
    points = _points_field(hardcore)
    # TRADEOFF: no index on the points columns, so each uncached page sorts every user; index
    # (is_active, <mode>_points) once the user count makes that sort show.
    return ranked_users().filter(**{f"{points}__gt": 0}).order_by(f"-{points}", "username")


def rank_by_points(hardcore, points):
    """Competition rank ("1224") of `points` in the mode, as `global_ranks` gives it."""
    return ranked_users().filter(**{f"{_points_field(hardcore)}__gt": points}).count() + 1


def ranked_users_page(hardcore, offset, count):
    """`(index, rank, user)` for `count` users of the mode's `ranking` after the first `offset`;
    tied points share the competition rank `rank_by_points` gives them."""
    points = _points_field(hardcore)
    return _competition_ranked(
        ranking(hardcore)[offset : offset + count],
        offset,
        value_of=lambda user: getattr(user, points),
        rank_of=lambda user_points: rank_by_points(hardcore, user_points),
    )


class RankingTally(NamedTuple):
    unlocked: int
    platinums: int


def ranking_tallies(user_ids, hardcore):
    """`{user_id: RankingTally}` for each of `user_ids`: the distinct official achievements
    unlocked in the mode, subsets included, and the platinums (core games with every official
    achievement unlocked in hardcore), whatever the mode."""
    per_game = list(
        official_unlocks()
        .filter(user_id__in=user_ids)
        .order_by()
        .values("user", "achievement__game")
        .annotate(
            unlocked=Count("achievement", filter=Q(hardcore=hardcore), distinct=True),
            hardcore_unlocked=Count("achievement", filter=Q(hardcore=True), distinct=True),
        )
        .values_list("user", "achievement__game", "unlocked", "hardcore_unlocked")
    )
    official_per_game = dict(
        Achievement.objects.filter(
            game_id__in={game_id for _, game_id, _, _ in per_game},
            game__set_type__isnull=True,
            status=Achievement.STATUS_OFFICIAL,
        )
        .order_by()
        .values("game")
        .annotate(count=Count("id"))
        .values_list("game", "count")
    )
    unlocked = dict.fromkeys(user_ids, 0)
    platinums = dict.fromkeys(user_ids, 0)
    for user_id, game_id, game_unlocked, hardcore_unlocked in per_game:
        unlocked[user_id] += game_unlocked
        # Unlocks are of the game's official achievements, so reaching its count is all of them;
        # a subset, or a game made unofficial between the two queries, has no count and no
        # platinum.
        if hardcore_unlocked == official_per_game.get(game_id):
            platinums[user_id] += 1
    return {
        user_id: RankingTally(unlocked=unlocked[user_id], platinums=platinums[user_id])
        for user_id in user_ids
    }


def ranked_player_counts():
    """How many users hold a rank in each mode: active, with points in it."""
    counts = ranked_users().aggregate(
        hardcore=Count("pk", filter=Q(hardcore_points__gt=0)),
        softcore=Count("pk", filter=Q(softcore_points__gt=0)),
    )
    return ByMode(hardcore=counts["hardcore"], softcore=counts["softcore"])


def unlocked_achievement_counts(user):
    """How many distinct official achievements the user unlocked in each mode."""
    counts = (
        official_unlocks()
        .filter(user=user)
        .aggregate(
            hardcore_unlocked=Count("achievement", filter=Q(hardcore=True), distinct=True),
            softcore_unlocked=Count("achievement", filter=Q(hardcore=False), distinct=True),
        )
    )
    return ByMode(hardcore=counts["hardcore_unlocked"], softcore=counts["softcore_unlocked"])


def games_played_count(user):
    """The core games the user played, on any of their discs or subsets."""
    return PlayerGame.objects.filter(user=user).aggregate(
        games=Count(Coalesce("game__parent_game", "game"), distinct=True)
    )["games"]


def _one_row_per_unlock(unlocks):
    """`unlocks` without the softcore twin a hardcore unlock writes at the same instant, so each
    unlock appears once. A softcore unlock earlier than the hardcore one is an unlock of its own.
    """
    hardcore_twin = UserUnlock.objects.filter(
        user=OuterRef("user"),
        achievement=OuterRef("achievement"),
        hardcore=True,
        unlocked_at=OuterRef("unlocked_at"),
    )
    return unlocks.filter(Q(hardcore=True) | ~Exists(hardcore_twin))


def recent_unlocks(user, limit):
    """The user's latest `limit` unlocks of official achievements, newest first, each once."""
    return (
        _one_row_per_unlock(official_unlocks().filter(user=user))
        .select_related("achievement__game__parent_game")
        .order_by("-unlocked_at", "-id")[:limit]
    )


def _active_users_unlocks():
    return _one_row_per_unlock(official_unlocks().filter(user__is_active=True))


def site_official_achievement_count():
    """How many official achievements there are, in core sets and subsets alike."""
    return Achievement.objects.filter(status=Achievement.STATUS_OFFICIAL).count()


def site_unlock_count():
    """How many unlocks of official achievements active users made, each once."""
    return _active_users_unlocks().count()


def _newest_first(unlocks, limit):
    return unlocks.select_related(
        "user", "achievement__game__console", "achievement__game__parent_game"
    ).order_by("-unlocked_at", "-id")[:limit]


def recent_site_unlocks(limit):
    """The latest `limit` unlocks of official achievements by active users, newest first, each
    once."""
    return _newest_first(_active_users_unlocks(), limit)


def recent_followed_unlocks(follower, limit):
    """`recent_site_unlocks` of the users `follower` follows only."""
    return _newest_first(_active_users_unlocks().filter(user__followed_by__user=follower), limit)


def official_games():
    """The core games with an official achievement, by title, each annotated with
    `official_achievements`, `official_points`, `player_count` (the active users with points
    who unlocked one of its official achievements, as `ranked_player_counts` counts players) and
    `subset_count`."""
    official = Q(achievements__status=Achievement.STATUS_OFFICIAL)
    # A subquery: counting players through a second join would multiply the achievement sums.
    player_count = (
        official_unlocks()
        .filter(achievement__game=OuterRef("pk"), user__is_active=True, user__softcore_points__gt=0)
        .order_by()
        .values("achievement__game")
        .annotate(count=Count("user", distinct=True))
        .values("count")
    )
    subset_count = (
        Game.objects.filter(parent_game=OuterRef("pk"))
        .order_by()
        .values("parent_game")
        .annotate(count=Count("pk"))
        .values("count")
    )
    return (
        Game.objects.core()
        .annotate(
            official_achievements=Count("achievements", filter=official),
            official_points=Sum("achievements__points", filter=official),
            player_count=Coalesce(Subquery(player_count), 0),
            subset_count=Coalesce(Subquery(subset_count), 0),
        )
        .filter(official_achievements__gt=0)
        .select_related("console")
        .order_by("title", "id")
    )


def catalog_games():
    """Every core game, each annotated with `official_achievements` and `played_by` (the active
    users who played it, as `game_players` lists them)."""
    played_by = (
        PlayerGame.objects.filter(game=OuterRef("pk"), user__is_active=True)
        .order_by()
        .values("game")
        .annotate(count=Count("pk"))
        .values("count")
    )
    return (
        Game.objects.core()
        .annotate(
            official_achievements=Count(
                "achievements", filter=Q(achievements__status=Achievement.STATUS_OFFICIAL)
            ),
            played_by=Coalesce(Subquery(played_by), 0),
        )
        .select_related("console")
    )


def playing_now():
    """The live sessions of active users, latest ping first."""
    return (
        PlayerGame.objects.playing_now()
        .filter(user__is_active=True)
        .select_related("user", "game__console")
        .order_by("-last_ping_at", "id")
    )


# Unlocking every official achievement of these types beats a game.
BEATING_TYPES = (Achievement.TYPE_PROGRESSION, Achievement.TYPE_WIN_CONDITION)


PERCENT = 100


def completion_percent(part, whole):
    """Floored, so 100% means every achievement and never a rounded-up 99.5%."""
    if whole == 0:
        return 0
    else:
        return part * PERCENT // whole


@dataclass
class SetProgress:
    """A user's progress on one set's official achievements. `complete` once every one is
    unlocked in hardcore: a core set's platinum, a subset's completion seal."""

    game: Game
    achievements: int
    unlocked: ByMode
    complete: bool


def set_progress(game, official_ids, hardcore_ids, softcore_ids):
    """`official_ids` are the set's official achievements; the id sets hold what the user
    unlocked in each mode, softcore covering both."""
    return SetProgress(
        game=game,
        achievements=len(official_ids),
        unlocked=ByMode(
            hardcore=len(official_ids & hardcore_ids), softcore=len(official_ids & softcore_ids)
        ),
        complete=bool(official_ids) and official_ids <= hardcore_ids,
    )


@dataclass
class GameProgress:
    """A user's progress on one played game's official achievements, with the subsets of the
    game the user started (an unlock in any mode), in site order."""

    played: PlayerGame
    achievements: int
    points: int
    unlocked: ByMode
    points_unlocked: int
    beaten: bool
    platinum: bool
    subsets: list[SetProgress]


def _game_progress(played, achievements, hardcore_ids, softcore_ids, subsets):
    """`achievements` are the game's official `(id, points, type)`; the id sets hold what the
    user unlocked in each mode, softcore covering both."""
    ids = {achievement_id for achievement_id, _, _ in achievements}
    beating_ids = {
        achievement_id
        for achievement_id, _, achievement_type in achievements
        if achievement_type in BEATING_TYPES
    }
    core = set_progress(played.game, ids, hardcore_ids, softcore_ids)
    return GameProgress(
        played=played,
        achievements=core.achievements,
        points=sum(points for _, points, _ in achievements),
        unlocked=core.unlocked,
        points_unlocked=sum(
            points for achievement_id, points, _ in achievements if achievement_id in softcore_ids
        ),
        beaten=bool(beating_ids) and beating_ids <= softcore_ids,
        platinum=core.complete,
        subsets=subsets,
    )


def _started_subsets(subsets, achievements_by_game, hardcore_ids, softcore_ids):
    progress = [
        set_progress(
            subset,
            {achievement_id for achievement_id, _, _ in achievements_by_game[subset.pk]},
            hardcore_ids,
            softcore_ids,
        )
        for subset in sorted(subsets, key=site_set_order)
    ]
    return [subset for subset in progress if subset.unlocked.softcore > 0]


def _core_play_record(core, records):
    """The user's play record of `core` from `records`, their rows on it and its subsets: the
    core row alone as is, else an unsaved sum. A specialty or exclusive disc is recorded on its
    own subset, so a player of that disc alone has no core row."""
    if len(records) == 1 and records[0].game_id == core.pk:
        return records[0]
    else:
        return PlayerGame(
            user_id=records[0].user_id,
            game=core,
            first_played_at=min(record.first_played_at for record in records),
            last_played_at=max(record.last_played_at for record in records),
            playtime_seconds=sum(record.playtime_seconds for record in records),
        )


def played_games_progress(user):
    """A `GameProgress` for each core game the user played, on any of its discs or subsets, most
    recently played first.

    A game is beaten once every official progression and win-condition achievement is unlocked
    in any mode, and platinum once every official achievement is unlocked in hardcore; a subset
    is complete once every official achievement of it is unlocked in hardcore.
    """
    records_by_core = {}
    for record in PlayerGame.objects.filter(user=user).select_related(
        "game__console", "game__parent_game__console"
    ):
        records_by_core.setdefault(record.game.core_game, []).append(record)
    played = sorted(
        (_core_play_record(core, records) for core, records in records_by_core.items()),
        key=lambda record: (-record.last_played_at.timestamp(), record.game_id),
    )
    core_ids = [played_game.game_id for played_game in played]
    subsets_by_core = {game_id: [] for game_id in core_ids}
    for subset in Game.objects.filter(parent_game_id__in=core_ids):
        subsets_by_core[subset.parent_game_id].append(subset)
    game_ids = core_ids + [subset.pk for subsets in subsets_by_core.values() for subset in subsets]
    achievements_by_game = {game_id: [] for game_id in game_ids}
    for achievement_id, game_id, points, achievement_type in Achievement.objects.filter(
        game_id__in=game_ids, status=Achievement.STATUS_OFFICIAL
    ).values_list("id", "game_id", "points", "type"):
        achievements_by_game[game_id].append((achievement_id, points, achievement_type))
    hardcore_ids = set()
    softcore_ids = set()
    for achievement_id, hardcore in (
        official_unlocks()
        .filter(user=user, achievement__game_id__in=game_ids)
        .values_list("achievement_id", "hardcore")
    ):
        if hardcore:
            hardcore_ids.add(achievement_id)
        else:
            softcore_ids.add(achievement_id)
    return [
        _game_progress(
            played_game,
            achievements_by_game[played_game.game_id],
            hardcore_ids,
            softcore_ids,
            _started_subsets(
                subsets_by_core[played_game.game_id],
                achievements_by_game,
                hardcore_ids,
                softcore_ids,
            ),
        )
        for played_game in played
    ]


def _unlocked_in_game(game, hardcore):
    """Counts, on a `PlayerGame`, the distinct official achievements of `game` its user
    unlocked in the mode."""
    return Count(
        "user__unlocks__achievement",
        filter=Q(
            user__unlocks__hardcore=hardcore,
            user__unlocks__achievement__game=game,
            user__unlocks__achievement__status=Achievement.STATUS_OFFICIAL,
        ),
        distinct=True,
    )


def game_players(game):
    """The active users who played `game`, most recently played first."""
    return PlayerGame.objects.filter(game=game, user__is_active=True).order_by(
        "-last_played_at", "id"
    )


def achievement_unlockers(achievement):
    """How many active users unlocked `achievement` in each mode; none while it is unofficial."""
    counts = (
        official_unlocks()
        .filter(achievement=achievement, user__is_active=True)
        .aggregate(
            hardcore=Count("user", filter=Q(hardcore=True), distinct=True),
            softcore=Count("user", distinct=True),
        )
    )
    return ByMode(hardcore=counts["hardcore"], softcore=counts["softcore"])


def game_players_with_progress(game, limit):
    """The first `limit` of `game_players`, each annotated with `hardcore_unlocked` and
    `softcore_unlocked`: the distinct official achievements of the game its user unlocked."""
    return (
        game_players(game)
        .select_related("user")
        .annotate(
            hardcore_unlocked=_unlocked_in_game(game, hardcore=True),
            softcore_unlocked=_unlocked_in_game(game, hardcore=False),
        )[:limit]
    )


def leaderboard_entries(leaderboard):
    """The leaderboard's entries by active users."""
    return leaderboard.entries.filter(user__is_active=True)


def game_leaderboards(games):
    """The leaderboards of `games`, each annotated with `entry_count`: its entries by active
    users."""
    return (
        Leaderboard.objects.filter(game__in=games)
        .annotate(entry_count=Count("entries", filter=Q(entries__user__is_active=True)))
        .order_by("id")
    )


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
    return _competition_ranked(
        board[offset : offset + count],
        offset,
        value_of=lambda entry: entry.score,
        rank_of=lambda score: rank_by_score(entries, lower_is_better, score),
    )


def _competition_ranked(items, offset, value_of, rank_of):
    """`(index, rank, item)` for `items`, the board positions after the first `offset`, best
    first.

    The first item takes `rank_of(its value)`, its rank on the whole board; each later one shares
    the rank of an equal value before it, else takes its 1-based `index`.
    """
    ranked = []
    previous_value = None
    previous_rank = None
    for index, item in enumerate(items, start=offset + 1):
        value = value_of(item)
        if previous_rank is None:
            rank = rank_of(value)
        elif value == previous_value:
            rank = previous_rank
        else:
            rank = index
        ranked.append((index, rank, item))
        previous_value = value
        previous_rank = rank
    return ranked
