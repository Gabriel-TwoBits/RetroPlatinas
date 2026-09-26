"""Checks on the emulator's unlock and leaderboard requests. They only flag `SuspiciousActivity`
rows for review; none of them bans anyone."""

import hashlib
import hmac
from datetime import timedelta

from django.core.cache import cache

from apps.achievements.models import UserUnlock
from apps.anticheat.models import SuspiciousActivity
from apps.games.models import PlayerGame

# rc_client sends one awardachievement per unlock; no set is played this fast.
AWARD_RATE_LIMIT = 30
AWARD_RATE_WINDOW = timedelta(minutes=1)
AWARD_RATE_KEY = "anticheat:award-attempts:{user_id}"

# This many achievements of one game unlocked within the window is flagged.
UNLOCK_BURST_THRESHOLD = 10
UNLOCK_BURST_WINDOW = timedelta(minutes=1)

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


def award_rate_exceeded(user):
    """Counts one award attempt by `user`: whether the window's attempts are past the limit.

    The first attempt past the limit is flagged, once per window.
    """
    key = AWARD_RATE_KEY.format(user_id=user.pk)
    window_seconds = int(AWARD_RATE_WINDOW.total_seconds())
    # TRADEOFF: fixed window, so a burst straddling two windows reaches twice the limit; a
    # sliding window (Redis sorted set) closes it.
    cache.add(key, 0, timeout=window_seconds)
    try:
        attempts = cache.incr(key)
    except ValueError:
        # The window expired between `add` and `incr`.
        cache.set(key, 1, timeout=window_seconds)
        attempts = 1
    if attempts == AWARD_RATE_LIMIT + 1:
        flag(
            user,
            SuspiciousActivity.Kind.RATE_LIMITED,
            limit=AWARD_RATE_LIMIT,
            window_seconds=window_seconds,
        )
    return attempts > AWARD_RATE_LIMIT


def inspect_unlock(user, achievement, unlocked_at, now):
    """Flags a new unlock that completes a burst or comes right after its session started."""
    _flag_unlock_burst(user, achievement.game_id, now)
    _flag_early_unlock(user, achievement, unlocked_at)


def _flag_unlock_burst(user, game_id, now):
    since = now - UNLOCK_BURST_WINDOW
    # Every award creates the softcore unlock, so softcore rows count each achievement once.
    unlocks = UserUnlock.objects.filter(
        user=user, hardcore=False, achievement__game_id=game_id, unlocked_at__gte=since
    ).count()
    # One flag per burst: the unlocks that keep it going are not flagged again.
    already_flagged = SuspiciousActivity.objects.filter(
        user=user,
        kind=SuspiciousActivity.Kind.UNLOCK_BURST,
        detail__game_id=game_id,
        created_at__gte=since,
    )
    if unlocks >= UNLOCK_BURST_THRESHOLD and not already_flagged.exists():
        flag(
            user,
            SuspiciousActivity.Kind.UNLOCK_BURST,
            game_id=game_id,
            unlocks=unlocks,
            window_seconds=int(UNLOCK_BURST_WINDOW.total_seconds()),
        )


def _flag_early_unlock(user, achievement, unlocked_at):
    session_started_at = (
        PlayerGame.objects.filter(user=user, game_id=achievement.game_id)
        .values_list("session_started_at", flat=True)
        .first()
    )
    # No recorded session (no startsession yet) leaves nothing to compare against.
    if session_started_at is not None and (
        timedelta(0) <= unlocked_at - session_started_at < EARLY_UNLOCK_WINDOW
    ):
        flag(
            user,
            SuspiciousActivity.Kind.EARLY_UNLOCK,
            game_id=achievement.game_id,
            achievement_id=achievement.pk,
            seconds_after_session_start=(unlocked_at - session_started_at).total_seconds(),
        )
