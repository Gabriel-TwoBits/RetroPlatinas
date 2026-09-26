"""Checks on the emulator's unlock and leaderboard requests. They only flag `SuspiciousActivity`
rows for review; none of them bans anyone."""

import hashlib
import hmac

from apps.anticheat.models import SuspiciousActivity


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
