"""Checks on the emulator's unlock and leaderboard requests. They only flag `SuspiciousActivity`
rows for review; none of them bans anyone."""

import hashlib
import hmac
from datetime import timedelta

from django.core.cache import cache

from apps.anticheat.models import SuspiciousActivity
from apps.games.models import PlayerGame

# rc_client sends one awardachievement per unlock; no set is played this fast.
AWARD_RATE_LIMIT = 30
AWARD_RATE_WINDOW = timedelta(minutes=1)
AWARD_RATE_KEY = "anticheat:award-attempts:{user_id}"

# This many achievements unlocked within the window in one game's sessions is flagged.
UNLOCK_BURST_THRESHOLD = 10
UNLOCK_BURST_WINDOW = timedelta(minutes=1)
UNLOCK_BURST_KEY = "anticheat:new-unlocks:{user_id}:{game_id}"

# A bad `v` is flagged once per user and action within this window, so a loop of bad requests
# cannot flood the review queue.
INVALID_SIGNATURE_FLAG_WINDOW = timedelta(minutes=1)
INVALID_SIGNATURE_KEY = "anticheat:invalid-signatures:{user_id}:{action}"

# rcheevos skips achievements already true when the game loads, so an unlock this soon after
# startsession needs a save state loaded near the trigger, or a forged request.
EARLY_UNLOCK_WINDOW = timedelta(seconds=30)


def _md5_hex(text):
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


def award_validation_hash(achievement_id, username, hardcore, seconds_since_unlock):
    """The `v` rcheevos signs an awardachievement with (`rc_api_init_award_achievement_request`).

    rcheevos sends `o` only when it is non-zero, and then signs it after a second copy of the
    achievement id.
    """
    if seconds_since_unlock:
        return _md5_hex(
            f"{achievement_id}{username}{int(hardcore)}{achievement_id}{seconds_since_unlock}"
        )
    else:
        return _md5_hex(f"{achievement_id}{username}{int(hardcore)}")


def leaderboard_validation_hash(leaderboard_id, username, score, seconds_since_completion):
    """The `v` rcheevos signs a submitlbentry with (`rc_api_init_submit_lboard_entry_request`).

    rcheevos sends `o` only when it is non-zero, and signs it only then.
    """
    if seconds_since_completion:
        return _md5_hex(f"{leaderboard_id}{username}{score}{seconds_since_completion}")
    else:
        return _md5_hex(f"{leaderboard_id}{username}{score}")


def signature_matches(expected, received):
    return hmac.compare_digest(expected.encode(), received.encode())


def flag(user, kind, **detail):
    return SuspiciousActivity.objects.create(user=user, kind=kind, detail=detail)


def _count_in_window(key, window):
    """Counts one event under `key`: the events since the window opened, on the first of them."""
    timeout = int(window.total_seconds())
    if cache.add(key, 1, timeout=timeout):
        return 1
    try:
        count = cache.incr(key)
    except ValueError:
        # The window expired between `add` and `incr`.
        cache.set(key, 1, timeout=timeout)
        return 1
    if count == 1:
        # The key expired between `incr`'s existence check and Redis INCR, which recreated it
        # without an expiry; left so, the window would never close.
        cache.touch(key, timeout)
    return count


def flag_invalid_signature(user, action, **detail):
    key = INVALID_SIGNATURE_KEY.format(user_id=user.pk, action=action)
    if _count_in_window(key, INVALID_SIGNATURE_FLAG_WINDOW) == 1:
        flag(user, SuspiciousActivity.Kind.INVALID_SIGNATURE, action=action, **detail)


def award_rate_exceeded(user):
    """Counts one award attempt by `user`: whether the window's attempts are past the limit.

    The first attempt past the limit is flagged, once per window.
    """
    # TRADEOFF: fixed window, so a burst straddling two windows reaches twice the limit; a
    # sliding window (Redis sorted set) closes it.
    attempts = _count_in_window(AWARD_RATE_KEY.format(user_id=user.pk), AWARD_RATE_WINDOW)
    if attempts == AWARD_RATE_LIMIT + 1:
        flag(
            user,
            SuspiciousActivity.Kind.RATE_LIMITED,
            limit=AWARD_RATE_LIMIT,
            window_seconds=int(AWARD_RATE_WINDOW.total_seconds()),
        )
    return attempts > AWARD_RATE_LIMIT


def inspect_unlock(user, achievement, session_game_id, seconds_since_unlock, now):
    """Flags a new unlock, arrived at `now`, that completes a burst or comes right after its
    session started.

    `session_game_id` is the game the session is recorded on, which the subsets served with a
    core set share with it.
    """
    _flag_unlock_burst(user, session_game_id)
    _flag_early_unlock(user, achievement, session_game_id, seconds_since_unlock, now)


def _flag_unlock_burst(user, game_id):
    # Counted as the unlocks arrive: their `unlocked_at` goes back by `o`, which whoever signs
    # `v` chooses.
    # TRADEOFF: the window opens on the first new unlock, so a burst straddling two windows is
    # split between them; a sliding window (Redis sorted set) closes it.
    unlocks = _count_in_window(
        UNLOCK_BURST_KEY.format(user_id=user.pk, game_id=game_id), UNLOCK_BURST_WINDOW
    )
    # One flag per burst: the unlocks that keep it going are not flagged again.
    if unlocks == UNLOCK_BURST_THRESHOLD:
        flag(
            user,
            SuspiciousActivity.Kind.UNLOCK_BURST,
            game_id=game_id,
            unlocks=unlocks,
            window_seconds=int(UNLOCK_BURST_WINDOW.total_seconds()),
        )


def _flag_early_unlock(user, achievement, session_game_id, seconds_since_unlock, now):
    session_started_at = (
        PlayerGame.objects.filter(user=user, game_id=session_game_id)
        .values_list("session_started_at", flat=True)
        .first()
    )
    # Judged on arrival, like the burst; `o` goes in the detail, as rc_client sends it only on
    # retries. No recorded session (no startsession yet) leaves nothing to compare against.
    if session_started_at is not None and now - session_started_at < EARLY_UNLOCK_WINDOW:
        flag(
            user,
            SuspiciousActivity.Kind.EARLY_UNLOCK,
            game_id=session_game_id,
            achievement_id=achievement.pk,
            seconds_after_session_start=(now - session_started_at).total_seconds(),
            seconds_since_unlock=seconds_since_unlock,
        )
