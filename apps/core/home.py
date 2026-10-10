"""What the home page shows, built from official sets, unlocks and live sessions."""

from apps.core import stats
from apps.images.catalog import avatar_path, badge_path, versioned_game_icon_path

RECENT_ACTIVITY_SHOWN = 8
PLAYING_NOW_SHOWN = 10


def _set(game):
    return {
        "game": game,
        "icon_url": versioned_game_icon_path(game),
        "achievements": game.official_achievements,
        "points": game.official_points,
        "players": game.player_count,
        "subsets": game.subset_count,
    }


def _activity():
    return [
        {"unlock": unlock, "badge_url": badge_path(unlock.achievement.badge_name)}
        for unlock in stats.recent_site_unlocks(RECENT_ACTIVITY_SHOWN)
    ]


def _playing_now():
    sessions = stats.playing_now()
    return {
        "total": sessions.count(),
        "sessions": [
            {"played": played, "avatar_url": avatar_path(played.user.username)}
            for played in sessions[:PLAYING_NOW_SHOWN]
        ],
    }


def home_context():
    # TRADEOFF: every official set, unpaginated; cap it with a link to /games/ once sets reach
    # dozens.
    sets = [_set(game) for game in stats.official_games()]
    return {
        "numbers": {
            "games": len(sets),
            "achievements": stats.site_official_achievement_count(),
            "players": stats.ranked_player_counts().softcore,
            "unlocks": stats.site_unlock_count(),
        },
        "sets": sets,
        "activity": _activity(),
        "playing_now": _playing_now(),
    }
