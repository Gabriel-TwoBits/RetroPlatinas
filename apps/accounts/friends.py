"""Following: who a user follows, who follows them, and the profile's follow control.

Only active users are listed or counted, as the ranking and the feed leave inactive ones out.
"""

from apps.accounts.models import Friendship
from apps.images.catalog import avatar_path

FOLLOW_ACTION_LOGIN = "login"
FOLLOW_ACTION_FOLLOW = "follow"
FOLLOW_ACTION_UNFOLLOW = "unfollow"


def _following_rows(user):
    return Friendship.objects.filter(user=user, friend__is_active=True)


def _follower_rows(user):
    return Friendship.objects.filter(friend=user, user__is_active=True)


def is_following(viewer, user):
    return viewer.is_authenticated and Friendship.objects.filter(user=viewer, friend=user).exists()


def _follow_action(profile_user, viewer, following):
    """The button the viewer gets on the profile, `None` for none.

    An inactive user cannot gain followers, but whoever already follows one can still stop.
    """
    if not viewer.is_authenticated:
        if profile_user.is_active:
            return FOLLOW_ACTION_LOGIN
        else:
            return None
    elif viewer.pk == profile_user.pk:
        return None
    elif following:
        return FOLLOW_ACTION_UNFOLLOW
    elif profile_user.is_active:
        return FOLLOW_ACTION_FOLLOW
    else:
        return None


def follow_context(profile_user, viewer):
    following = is_following(viewer, profile_user)
    return {
        "profile_user": profile_user,
        "following_count": _following_rows(profile_user).count(),
        "follower_count": _follower_rows(profile_user).count(),
        "follow_action": _follow_action(profile_user, viewer, following),
    }


def _user_row(user):
    return {"user": user, "avatar_url": avatar_path(user.username)}


def friends_context(profile_user):
    """Whom `profile_user` follows and who follows them, most recent follow first."""
    # TRADEOFF: both lists unpaginated; page them if players reach hundreds of follows.
    following = (
        _following_rows(profile_user).select_related("friend").order_by("-created_at", "-id")
    )
    followers = _follower_rows(profile_user).select_related("user").order_by("-created_at", "-id")
    return {
        "profile_user": profile_user,
        "following": [_user_row(friendship.friend) for friendship in following],
        "followers": [_user_row(friendship.user) for friendship in followers],
    }
