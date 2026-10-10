"""Following other users: the model, the profile's follow control and the friends page."""

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import Friendship
from apps.images.catalog import avatar_path

User = get_user_model()

PASSWORD = "pw-secret-123"
HARDCORE_POINTS = 1234
SOFTCORE_POINTS = 2345
PROFILE_PATH = "/users/bob/"
FOLLOW_PATH = "/users/bob/follow/"
UNFOLLOW_PATH = "/users/bob/unfollow/"
FRIENDS_PATH = "/users/alice/friends/"
HTMX = {"HTTP_HX_REQUEST": "true", "HTTP_HX_CURRENT_URL": f"http://testserver{PROFILE_PATH}"}


def _user(username, is_active=True, **fields):
    return User.objects.create_user(
        username=username, password=PASSWORD, is_active=is_active, **fields
    )


def _follow(user, friend, days_ago=0):
    friendship = Friendship.objects.create(user=user, friend=friend)
    Friendship.objects.filter(pk=friendship.pk).update(
        created_at=timezone.now() - timedelta(days=days_ago)
    )


def _get(client, path):
    return client.get(path, HTTP_ACCEPT_LANGUAGE="en")


def _post(client, path, **headers):
    return client.post(path, HTTP_ACCEPT_LANGUAGE="en", **headers)


def _follows(user, friend):
    return Friendship.objects.filter(user=user, friend=friend).exists()


@pytest.fixture
def alice(db):
    return _user("alice")


@pytest.fixture
def bob(db):
    return _user("bob")


# --- Model ---


@pytest.mark.django_db
def test_a_user_follows_another_once(alice, bob):
    Friendship.objects.create(user=alice, friend=bob)
    with pytest.raises(IntegrityError), transaction.atomic():
        Friendship.objects.create(user=alice, friend=bob)


@pytest.mark.django_db
def test_following_is_one_way(alice, bob):
    Friendship.objects.create(user=alice, friend=bob)
    Friendship.objects.create(user=bob, friend=alice)
    assert Friendship.objects.count() == 2


@pytest.mark.django_db
def test_a_user_cannot_follow_themselves(alice):
    with pytest.raises(IntegrityError), transaction.atomic():
        Friendship.objects.create(user=alice, friend=alice)


# --- Follow and unfollow ---


@pytest.mark.django_db
def test_follow_creates_the_relation_and_returns_to_the_profile(client, alice, bob):
    client.force_login(alice)

    resp = _post(client, FOLLOW_PATH)

    assert resp.status_code == HTTPStatus.FOUND
    assert resp.url == PROFILE_PATH
    assert _follows(alice, bob)
    assert not _follows(bob, alice)


@pytest.mark.django_db
def test_follow_with_htmx_swaps_the_control_with_the_new_count(client, alice, bob):
    client.force_login(alice)

    resp = _post(client, FOLLOW_PATH, **HTMX)

    body = resp.content.decode()
    assert resp.status_code == HTTPStatus.OK
    assert 'id="follow-control"' in body
    assert "<html" not in body
    assert "1 follower" in body
    assert f'hx-post="{UNFOLLOW_PATH}"' in body
    assert f'hx-post="{FOLLOW_PATH}"' not in body


@pytest.mark.django_db
def test_following_twice_keeps_one_relation(client, alice, bob):
    client.force_login(alice)
    _post(client, FOLLOW_PATH)
    _post(client, FOLLOW_PATH)
    assert Friendship.objects.filter(user=alice, friend=bob).count() == 1


@pytest.mark.django_db
def test_follow_refuses_yourself(client, bob):
    client.force_login(bob)

    resp = _post(client, FOLLOW_PATH)

    assert resp.status_code == HTTPStatus.BAD_REQUEST
    assert not Friendship.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/users/nobody/follow/", "/users/ra-import/follow/"])
def test_follow_404s_for_an_unknown_or_inactive_user(client, alice, path):
    _user("ra-import", is_active=False)
    client.force_login(alice)

    assert _post(client, path).status_code == HTTPStatus.NOT_FOUND
    assert not Friendship.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("path", [FOLLOW_PATH, UNFOLLOW_PATH])
def test_follow_and_unfollow_send_an_anonymous_visitor_to_log_in(client, bob, path):
    resp = _post(client, path)

    assert resp.status_code == HTTPStatus.FOUND
    assert resp.url == f"/login/?next={path}"
    assert not Friendship.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize("path", [FOLLOW_PATH, UNFOLLOW_PATH])
def test_htmx_follow_with_an_expired_session_returns_to_the_profile_after_login(client, bob, path):
    resp = _post(client, path, **HTMX)

    assert resp.status_code == HTTPStatus.OK
    assert resp["HX-Redirect"] == f"/login/?next={PROFILE_PATH}"


@pytest.mark.django_db
@pytest.mark.parametrize("path", [FOLLOW_PATH, UNFOLLOW_PATH])
def test_follow_and_unfollow_only_accept_post(client, alice, bob, path):
    client.force_login(alice)
    assert _get(client, path).status_code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_unfollow_removes_only_the_viewers_relation(client, alice, bob):
    carol = _user("carol")
    Friendship.objects.create(user=alice, friend=bob)
    Friendship.objects.create(user=carol, friend=bob)
    client.force_login(alice)

    resp = _post(client, UNFOLLOW_PATH, **HTMX)

    assert resp.status_code == HTTPStatus.OK
    assert not _follows(alice, bob)
    assert _follows(carol, bob)
    body = resp.content.decode()
    assert "1 follower" in body
    assert f'hx-post="{FOLLOW_PATH}"' in body


@pytest.mark.django_db
def test_unfollow_without_following_changes_nothing(client, alice, bob):
    client.force_login(alice)

    resp = _post(client, UNFOLLOW_PATH)

    assert resp.status_code == HTTPStatus.FOUND
    assert not Friendship.objects.exists()


@pytest.mark.django_db
def test_unfollow_works_on_an_inactive_user(client, alice, bob):
    Friendship.objects.create(user=alice, friend=bob)
    User.objects.filter(pk=bob.pk).update(is_active=False)
    client.force_login(alice)

    assert _post(client, UNFOLLOW_PATH).status_code == HTTPStatus.FOUND
    assert not _follows(alice, bob)


@pytest.mark.django_db
def test_unfollow_404s_for_an_unknown_user(client, alice):
    client.force_login(alice)
    assert _post(client, "/users/nobody/unfollow/").status_code == HTTPStatus.NOT_FOUND


# --- Profile follow control ---


@pytest.mark.django_db
def test_profile_shows_follower_and_following_counts_of_active_users(client, alice, bob):
    carol = _user("carol")
    gone = _user("gone")
    Friendship.objects.create(user=alice, friend=bob)
    Friendship.objects.create(user=carol, friend=bob)
    Friendship.objects.create(user=gone, friend=bob)
    Friendship.objects.create(user=bob, friend=alice)
    User.objects.filter(pk=gone.pk).update(is_active=False)

    body = _get(client, PROFILE_PATH).content.decode()

    assert "2 followers" in body
    assert "1 following" in body
    assert 'href="/users/bob/friends/"' in body


@pytest.mark.django_db
def test_anonymous_visitor_gets_a_follow_link_to_log_in(client, bob):
    body = _get(client, PROFILE_PATH).content.decode()

    assert f'href="/login/?next={PROFILE_PATH}"' in body
    assert "hx-post" not in body


@pytest.mark.django_db
def test_owner_gets_no_follow_button(client, bob):
    client.force_login(bob)

    body = _get(client, PROFILE_PATH).content.decode()

    assert FOLLOW_PATH not in body
    assert UNFOLLOW_PATH not in body


@pytest.mark.django_db
def test_visitor_gets_follow_then_unfollow(client, alice, bob):
    client.force_login(alice)
    assert f'hx-post="{FOLLOW_PATH}"' in _get(client, PROFILE_PATH).content.decode()

    Friendship.objects.create(user=alice, friend=bob)

    body = _get(client, PROFILE_PATH).content.decode()
    assert f'hx-post="{UNFOLLOW_PATH}"' in body
    assert f'hx-post="{FOLLOW_PATH}"' not in body


@pytest.mark.django_db
def test_inactive_profile_offers_only_an_unfollow(client, alice, bob):
    User.objects.filter(pk=bob.pk).update(is_active=False)
    client.force_login(alice)
    assert FOLLOW_PATH not in _get(client, PROFILE_PATH).content.decode()

    Friendship.objects.create(user=alice, friend=bob)

    assert f'hx-post="{UNFOLLOW_PATH}"' in _get(client, PROFILE_PATH).content.decode()


@pytest.mark.django_db
def test_follow_control_renders_in_brazilian_portuguese(client, alice, bob):
    Friendship.objects.create(user=alice, friend=bob)
    client.force_login(alice)

    body = client.get(PROFILE_PATH, HTTP_ACCEPT_LANGUAGE="pt-br").content.decode()

    assert "1 seguidor" in body
    assert "Deixar de seguir" in body


# --- Friends page ---


@pytest.mark.django_db
def test_friends_page_lists_following_and_followers_newest_first(client, alice, bob):
    carol = _user("carol", hardcore_points=HARDCORE_POINTS, softcore_points=SOFTCORE_POINTS)
    dave = _user("dave")
    _follow(alice, bob, days_ago=2)
    _follow(alice, carol, days_ago=1)
    _follow(dave, alice, days_ago=1)
    _follow(bob, alice, days_ago=0)
    _follow(bob, carol)

    resp = _get(client, FRIENDS_PATH)

    assert resp.status_code == HTTPStatus.OK
    assert [row["user"] for row in resp.context["following"]] == [carol, bob]
    assert [row["user"] for row in resp.context["followers"]] == [bob, dave]
    body = resp.content.decode()
    assert "alice's friends" in body
    assert 'href="/users/carol/"' in body
    assert f'src="{avatar_path("carol")}"' in body
    assert "1,234 hardcore pts" in body
    assert "2,345 softcore pts" in body


@pytest.mark.django_db
def test_friends_page_leaves_out_inactive_users(client, alice, bob):
    Friendship.objects.create(user=alice, friend=bob)
    Friendship.objects.create(user=bob, friend=alice)
    User.objects.filter(pk=bob.pk).update(is_active=False)

    resp = _get(client, FRIENDS_PATH)

    assert resp.context["following"] == []
    assert resp.context["followers"] == []


@pytest.mark.django_db
def test_friends_page_shows_empty_states(client, alice):
    body = _get(client, FRIENDS_PATH).content.decode()

    assert "Not following anyone yet" in body
    assert "No followers yet" in body


@pytest.mark.django_db
def test_friends_page_404s_for_an_unknown_user(client):
    assert _get(client, "/users/nobody/friends/").status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_friends_page_rejects_a_post(client, alice):
    assert _post(client, FRIENDS_PATH).status_code == HTTPStatus.METHOD_NOT_ALLOWED
