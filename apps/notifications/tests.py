"""Notifications to an achievement's author: emitted on a comment, an unlock and a status change,
never for what the author did; listed in the header's bell and on /notifications/, rendered in
the reader's language, and marked read one at a time or all at once."""

from datetime import timedelta
from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import API_TOKEN_HEX_LENGTH
from apps.achievements.models import Achievement
from apps.achievements.revisions import revert
from apps.anticheat.detection import award_validation_hash
from apps.games.models import Console, Game
from apps.notifications.display import (
    MENU_NOTIFICATIONS_SHOWN,
    NOTIFICATIONS_PER_PAGE,
    POLL_SECONDS,
    message,
)
from apps.notifications.models import Notification
from apps.notifications.views import HTMX_STOP_POLLING

User = get_user_model()

PLAYSTATION_RA_ID = 12
PASSWORD = "pw-secret-123"
ACHIEVEMENT_POINTS = 5
UNKNOWN_ID = 999_999
API_TOKEN = "t" * API_TOKEN_HEX_LENGTH
API_TOKEN_DAYS = 14
HTMX = {"HTTP_HX_REQUEST": "true"}
ACHIEVEMENT_CHANGELIST_URL = "/admin/achievements/achievement/"
EDITOR_TRIGGER = "0xH61998=1_d0xH61998=0"
LIST_URL = reverse("notification_list")
UNREAD_URL = reverse("notification_unread_count")
MENU_URL = reverse("notification_menu")
READ_ALL_URL = reverse("notification_read_all")


def _user(username, is_staff=False):
    return User.objects.create_user(username=username, password=PASSWORD, is_staff=is_staff)


@pytest.fixture
def author(db):
    return _user("author")


@pytest.fixture
def other(db):
    return _user("other")


@pytest.fixture
def staff(db):
    return _user("staff", is_staff=True)


@pytest.fixture
def inactive_author(db):
    """Like the seeded achievements' import account, which cannot log in."""
    return User.objects.create_user(username="ra-import", is_active=False)


@pytest.fixture
def game(db):
    console = Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


def _achievement(game, author, status=Achievement.STATUS_OFFICIAL, title="Beach"):
    return Achievement.objects.create(
        game=game,
        author=author,
        title=title,
        description="Clear the beach",
        points=ACHIEVEMENT_POINTS,
        mem_addr="0xH0001=1",
        status=status,
    )


@pytest.fixture
def achievement(game, author):
    return _achievement(game, author)


def _achievement_url(achievement):
    return reverse("achievement_detail", args=[achievement.game_id, achievement.pk])


def _notification(user, kind=Notification.KIND_COMMENT, read=False, **params):
    return Notification.objects.create(
        user=user,
        kind=kind,
        params=params or {"actor": "other", "achievement": "Beach"},
        target_url="/games/1/achievements/1/",
        read=read,
    )


def _get(client, url, **extra):
    return client.get(url, HTTP_ACCEPT_LANGUAGE="en", **extra)


def _post(client, url, data=None, **extra):
    return client.post(url, data or {}, HTTP_ACCEPT_LANGUAGE="en", **extra)


def _unread_count(client):
    response = _get(client, UNREAD_URL, **HTMX)
    assert response.status_code == HTTPStatus.OK
    return response.content.decode()


# --- Comments ---


@pytest.mark.django_db
def test_a_comment_on_an_achievement_notifies_its_author(client, author, other, achievement):
    client.force_login(other)

    _post(
        client,
        reverse("achievement_comment_add", args=[achievement.game_id, achievement.pk]),
        {"content": "Nice one"},
        **HTMX,
    )

    notification = Notification.objects.get()
    assert notification.user == author
    assert notification.kind == Notification.KIND_COMMENT
    assert notification.params == {"actor": "other", "achievement": "Beach"}
    assert notification.target_url == f"{_achievement_url(achievement)}#comments"
    assert notification.read is False


@pytest.mark.django_db
def test_commenting_on_your_own_achievement_notifies_nobody(client, author, achievement):
    client.force_login(author)

    _post(
        client,
        reverse("achievement_comment_add", args=[achievement.game_id, achievement.pk]),
        {"content": "Mine"},
        **HTMX,
    )

    assert not Notification.objects.exists()


@pytest.mark.django_db
def test_a_comment_on_an_inactive_authors_achievement_notifies_nobody(
    client, other, game, inactive_author
):
    achievement = _achievement(game, inactive_author)
    client.force_login(other)

    _post(
        client,
        reverse("achievement_comment_add", args=[achievement.game_id, achievement.pk]),
        {"content": "Nice one"},
        **HTMX,
    )

    assert not Notification.objects.exists()


@pytest.mark.django_db
def test_a_comment_on_a_game_notifies_nobody(client, other, game):
    client.force_login(other)

    _post(client, reverse("game_comment_add", args=[game.pk]), {"content": "Great game"}, **HTMX)

    assert not Notification.objects.exists()


@pytest.mark.django_db
def test_an_invalid_comment_notifies_nobody(client, other, achievement):
    client.force_login(other)

    _post(
        client,
        reverse("achievement_comment_add", args=[achievement.game_id, achievement.pk]),
        {"content": ""},
        **HTMX,
    )

    assert not Notification.objects.exists()


# --- Unlocks ---


@pytest.fixture
def player(db):
    user = _user("player")
    user.api_token = API_TOKEN
    user.api_token_expires_at = timezone.now() + timedelta(days=API_TOKEN_DAYS)
    user.save(update_fields=["api_token", "api_token_expires_at"])
    return user


def _award(client, player, achievement, hardcore):
    return client.post(
        "/dorequest.php",
        {
            "r": "awardachievement",
            "u": player.username,
            "t": API_TOKEN,
            "a": achievement.pk,
            "h": hardcore,
            "v": award_validation_hash(achievement.pk, player.username, hardcore == "1", 0),
        },
    )


@pytest.mark.django_db
def test_an_unlock_notifies_the_achievements_author_once(client, author, player, achievement):
    assert _award(client, player, achievement, "0").json()["Success"] is True
    _award(client, player, achievement, "0")
    _award(client, player, achievement, "1")

    notification = Notification.objects.get()
    assert notification.user == author
    assert notification.kind == Notification.KIND_UNLOCK
    assert notification.params == {"actor": "player", "achievement": "Beach"}
    assert notification.target_url == _achievement_url(achievement)


@pytest.mark.django_db
def test_a_hardcore_first_unlock_notifies_once(client, author, player, achievement):
    _award(client, player, achievement, "1")

    assert Notification.objects.filter(user=author, kind=Notification.KIND_UNLOCK).count() == 1


@pytest.mark.django_db
def test_unlocking_your_own_achievement_notifies_nobody(client, player, game):
    own = _achievement(game, player)

    assert _award(client, player, own, "0").json()["Success"] is True

    assert not Notification.objects.exists()


@pytest.mark.django_db
def test_unlocking_an_inactive_authors_achievement_notifies_nobody(
    client, player, game, inactive_author
):
    achievement = _achievement(game, inactive_author)

    assert _award(client, player, achievement, "0").json()["Success"] is True

    assert not Notification.objects.exists()


@pytest.mark.django_db
def test_the_unlock_notification_adds_one_insert_to_the_award(client, author, player, achievement):
    own = _achievement(achievement.game, player, title="Own")
    warm_up = _achievement(achievement.game, player, title="Warm-up")
    # The game's first award also records the player; the measured ones only update it.
    _award(client, player, warm_up, "0")

    with CaptureQueriesContext(connection) as without_notification:
        _award(client, player, own, "0")
    with CaptureQueriesContext(connection) as with_notification:
        _award(client, player, achievement, "0")

    assert len(with_notification) == len(without_notification) + 1


# --- Status changes ---


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("action", "start", "end"),
    [
        ("make_unofficial", Achievement.STATUS_OFFICIAL, Achievement.STATUS_UNOFFICIAL),
        ("make_official", Achievement.STATUS_UNOFFICIAL, Achievement.STATUS_OFFICIAL),
    ],
)
def test_an_admin_status_action_notifies_each_author(
    admin_client, author, other, game, action, start, end
):
    mine = _achievement(game, author, status=start, title="Mine")
    theirs = _achievement(game, other, status=start, title="Theirs")

    admin_client.post(
        ACHIEVEMENT_CHANGELIST_URL, {"action": action, "_selected_action": [mine.pk, theirs.pk]}
    )

    notifications = Notification.objects.filter(kind=Notification.KIND_STATUS)
    assert {(n.user_id, n.params["achievement"]) for n in notifications} == {
        (author.pk, "Mine"),
        (other.pk, "Theirs"),
    }
    assert all(
        n.params["old_status"] == start and n.params["new_status"] == end for n in notifications
    )


@pytest.mark.django_db
def test_an_admin_status_action_notifies_no_inactive_author(admin_client, game, inactive_author):
    achievement = _achievement(game, inactive_author)

    admin_client.post(
        ACHIEVEMENT_CHANGELIST_URL,
        {"action": "make_unofficial", "_selected_action": [achievement.pk]},
    )

    assert not Notification.objects.exists()


@pytest.mark.django_db
def test_an_admin_action_that_changes_nothing_notifies_nobody(admin_client, achievement):
    admin_client.post(
        ACHIEVEMENT_CHANGELIST_URL,
        {"action": "make_official", "_selected_action": [achievement.pk]},
    )

    assert not Notification.objects.exists()


@pytest.mark.django_db
def test_the_admin_change_form_status_change_notifies_the_author(admin_client, achievement):
    admin_client.post(
        f"{ACHIEVEMENT_CHANGELIST_URL}{achievement.pk}/change/",
        {
            "game": achievement.game_id,
            "author": achievement.author_id,
            "title": achievement.title,
            "description": achievement.description,
            "points": achievement.points,
            "mem_addr": achievement.mem_addr,
            "status": Achievement.STATUS_UNOFFICIAL,
            "badge_name": achievement.badge_name,
        },
    )

    notification = Notification.objects.get()
    assert notification.user == achievement.author
    assert notification.params["new_status"] == Achievement.STATUS_UNOFFICIAL


def _edit(client, achievement, status):
    return _post(
        client,
        reverse("achievement_edit", args=[achievement.game_id, achievement.pk]),
        {
            "title": achievement.title,
            "description": achievement.description,
            "points": achievement.points,
            "type": achievement.type,
            "mem_addr": EDITOR_TRIGGER,
            "status": status,
        },
    )


@pytest.mark.django_db
def test_staff_changing_the_status_in_the_editor_notifies_the_author(client, staff, achievement):
    client.force_login(staff)

    response = _edit(client, achievement, Achievement.STATUS_UNOFFICIAL)

    assert response.status_code == HTTPStatus.FOUND
    notification = Notification.objects.get()
    assert notification.user == achievement.author
    assert notification.kind == Notification.KIND_STATUS
    assert notification.target_url == _achievement_url(achievement)


@pytest.mark.django_db
def test_the_author_changing_their_own_status_notifies_nobody(client, author, achievement):
    client.force_login(author)

    response = _edit(client, achievement, Achievement.STATUS_UNOFFICIAL)

    assert response.status_code == HTTPStatus.FOUND
    assert not Notification.objects.exists()


@pytest.mark.django_db
def test_an_edit_that_keeps_the_status_notifies_nobody(client, staff, achievement):
    client.force_login(staff)

    _edit(client, achievement, Achievement.STATUS_OFFICIAL)

    assert not Notification.objects.exists()


@pytest.mark.django_db
def test_a_staff_revert_that_restores_another_status_notifies_the_author(staff, achievement):
    first = achievement.revisions.get()
    achievement.status = Achievement.STATUS_UNOFFICIAL
    achievement.save(editor=staff)
    Notification.objects.all().delete()

    revert(achievement, first, staff)

    notification = Notification.objects.get()
    assert notification.params["old_status"] == Achievement.STATUS_UNOFFICIAL
    assert notification.params["new_status"] == Achievement.STATUS_OFFICIAL


@pytest.mark.django_db
def test_a_status_change_by_an_unknown_editor_notifies_the_author(author, achievement):
    achievement.status = Achievement.STATUS_UNOFFICIAL
    achievement.save()

    notification = Notification.objects.get()
    assert notification.user == author
    assert notification.kind == Notification.KIND_STATUS
    assert notification.params["new_status"] == Achievement.STATUS_UNOFFICIAL


@pytest.mark.django_db
def test_creating_an_achievement_notifies_nobody(game, author):
    _achievement(game, author, status=Achievement.STATUS_OFFICIAL)

    assert not Notification.objects.exists()


# --- Messages ---


@pytest.mark.django_db
def test_messages_are_rendered_in_the_readers_language(client, author):
    _notification(author, Notification.KIND_UNLOCK)
    _notification(author, Notification.KIND_COMMENT)
    client.force_login(author)

    english = _get(client, LIST_URL).content.decode()
    portuguese = client.get(LIST_URL, HTTP_ACCEPT_LANGUAGE="pt-br").content.decode()

    assert "other commented on your achievement “Beach”." in english
    assert "other unlocked your achievement “Beach”." in english
    assert "other comentou na sua conquista “Beach”." in portuguese
    assert "other desbloqueou a sua conquista “Beach”." in portuguese


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("old_status", "new_status", "english", "portuguese"),
    [
        (
            Achievement.STATUS_UNOFFICIAL,
            Achievement.STATUS_OFFICIAL,
            "Your achievement “Beach” is now official.",
            "Sua conquista “Beach” agora é oficial.",
        ),
        (
            Achievement.STATUS_OFFICIAL,
            Achievement.STATUS_UNOFFICIAL,
            "Your achievement “Beach” is now unofficial.",
            "Sua conquista “Beach” deixou de ser oficial.",
        ),
    ],
)
def test_status_messages_name_the_new_status_in_the_readers_language(
    client, author, old_status, new_status, english, portuguese
):
    _notification(
        author,
        Notification.KIND_STATUS,
        achievement="Beach",
        old_status=old_status,
        new_status=new_status,
    )
    client.force_login(author)

    assert english in _get(client, LIST_URL).content.decode()
    assert portuguese in client.get(LIST_URL, HTTP_ACCEPT_LANGUAGE="pt-br").content.decode()


@pytest.mark.django_db
def test_a_status_message_with_an_unknown_status_fails_loudly(author):
    notification = _notification(
        author,
        Notification.KIND_STATUS,
        achievement="Beach",
        old_status=Achievement.STATUS_OFFICIAL,
        new_status="verified",
    )

    with pytest.raises(ValueError, match="unknown status 'verified'"):
        message(notification)


@pytest.mark.django_db
def test_messages_escape_their_parameters(client, author):
    _notification(author, actor="<b>evil</b>", achievement="Beach")
    client.force_login(author)

    page = _get(client, LIST_URL).content.decode()

    assert "&lt;b&gt;evil&lt;/b&gt;" in page
    assert "<b>evil</b>" not in page


# --- Acceptance: A comments on B's achievement, B reads it, the counter resets ---


@pytest.mark.django_db
def test_b_sees_a_comment_by_a_reads_it_and_the_counter_resets(client, author, other, achievement):
    client.force_login(other)
    _post(
        client,
        reverse("achievement_comment_add", args=[achievement.game_id, achievement.pk]),
        {"content": "Nice one"},
        **HTMX,
    )
    client.force_login(author)

    assert "1" in _unread_count(client)
    assert "other commented on your achievement" in _get(client, MENU_URL, **HTMX).content.decode()

    notification = Notification.objects.get()
    response = _post(client, reverse("notification_read", args=[notification.pk]))

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == f"{_achievement_url(achievement)}#comments"
    notification.refresh_from_db()
    assert notification.read is True
    assert _unread_count(client).strip() == ""


# --- Bell ---


@pytest.mark.django_db
def test_the_header_shows_the_bell_with_the_unread_count(client, author):
    _notification(author)
    _notification(author)
    _notification(author, read=True)
    client.force_login(author)

    page = _get(client, reverse("home")).content.decode()

    assert 'id="notification-menu"' in page
    assert "2 unread notifications" in page
    assert f'hx-get="{UNREAD_URL}" hx-trigger="every {POLL_SECONDS}s"' in page


@pytest.mark.django_db
def test_an_anonymous_visitor_gets_no_bell(client):
    page = _get(client, reverse("home")).content.decode()

    assert 'id="notification-menu"' not in page


@pytest.mark.django_db
def test_the_unread_count_counts_only_the_users_unread_notifications(client, author, other):
    _notification(author)
    _notification(author, read=True)
    _notification(other)
    client.force_login(author)

    assert "1 unread notification<" in _unread_count(client)


@pytest.mark.django_db
def test_the_unread_count_stops_polling_once_logged_out(client):
    response = _get(client, UNREAD_URL, **HTMX)

    assert response.status_code == HTMX_STOP_POLLING
    assert response.content == b""


@pytest.mark.django_db
def test_the_menu_lists_the_latest_notifications(client, author, other):
    for number in range(MENU_NOTIFICATIONS_SHOWN + 1):
        _notification(author, actor=f"player{number}", achievement="Beach")
    _notification(other, actor="stranger", achievement="Other")
    client.force_login(author)

    menu = _get(client, MENU_URL, **HTMX).content.decode()

    assert menu.count("<li") == MENU_NOTIFICATIONS_SHOWN
    assert f"player{MENU_NOTIFICATIONS_SHOWN}" in menu
    assert "player0 " not in menu
    assert "stranger" not in menu


@pytest.mark.django_db
def test_the_menu_shows_the_empty_state(client, author):
    client.force_login(author)

    assert "No notifications yet" in _get(client, MENU_URL, **HTMX).content.decode()


@pytest.mark.django_db
def test_the_menu_reloads_the_page_once_logged_out(client):
    response = _get(client, MENU_URL, **HTMX)

    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert response["HX-Refresh"] == "true"


# --- Page ---


@pytest.mark.django_db
def test_the_page_requires_login(client):
    response = _get(client, LIST_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"].startswith(reverse("login"))


@pytest.mark.django_db
def test_the_page_lists_the_users_notifications_newest_first(client, author, other):
    _notification(author, actor="older", achievement="Beach")
    _notification(author, actor="newer", achievement="Beach")
    _notification(other, actor="stranger", achievement="Other")
    client.force_login(author)

    page = _get(client, LIST_URL).content.decode()

    assert page.index("newer") < page.index("older")
    assert "stranger" not in page
    assert "Mark all as read" in page


@pytest.mark.django_db
def test_the_page_shows_the_empty_state_without_mark_all(client, author):
    client.force_login(author)

    page = _get(client, LIST_URL).content.decode()

    assert "No notifications yet" in page
    assert "Mark all as read" not in page


@pytest.mark.django_db
def test_the_page_is_paginated(client, author):
    for number in range(NOTIFICATIONS_PER_PAGE + 1):
        _notification(author, actor=f"player{number}", achievement="Beach")
    client.force_login(author)

    first = _get(client, LIST_URL).content.decode()
    second = _get(client, f"{LIST_URL}?page=2").content.decode()

    assert "Page 1 of 2" in first
    assert "player0 " not in first
    assert "player0 " in second


@pytest.mark.django_db
@pytest.mark.parametrize("page", ["3", "x", "0"])
def test_an_unknown_page_is_404(client, author, page):
    _notification(author)
    client.force_login(author)

    assert _get(client, f"{LIST_URL}?page={page}").status_code == HTTPStatus.NOT_FOUND


# --- Marking read ---


@pytest.mark.django_db
def test_marking_another_users_notification_is_404(client, author, other):
    theirs = _notification(other)
    client.force_login(author)

    response = _post(client, reverse("notification_read", args=[theirs.pk]))

    assert response.status_code == HTTPStatus.NOT_FOUND
    theirs.refresh_from_db()
    assert theirs.read is False


@pytest.mark.django_db
def test_marking_an_unknown_notification_is_404(client, author):
    client.force_login(author)

    response = _post(client, reverse("notification_read", args=[UNKNOWN_ID]))

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_marking_read_needs_a_post(client, author):
    notification = _notification(author)
    client.force_login(author)

    response = _get(client, reverse("notification_read", args=[notification.pk]))

    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    notification.refresh_from_db()
    assert notification.read is False


@pytest.mark.django_db
def test_marking_read_never_redirects_off_site(client, author):
    notification = _notification(author)
    Notification.objects.filter(pk=notification.pk).update(target_url="https://evil.example/")
    client.force_login(author)

    response = _post(client, reverse("notification_read", args=[notification.pk]))

    assert response["Location"] == LIST_URL


@pytest.mark.django_db
def test_marking_read_requires_login(client, author):
    notification = _notification(author)

    response = _post(client, reverse("notification_read", args=[notification.pk]))

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"].startswith(reverse("login"))
    notification.refresh_from_db()
    assert notification.read is False


@pytest.mark.django_db
def test_marking_all_read_resets_only_the_users_counter(client, author, other):
    _notification(author)
    _notification(author)
    theirs = _notification(other)
    client.force_login(author)

    response = _post(client, READ_ALL_URL)

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == LIST_URL
    assert not Notification.objects.filter(user=author, read=False).exists()
    theirs.refresh_from_db()
    assert theirs.read is False
    assert _unread_count(client).strip() == ""


@pytest.mark.django_db
def test_marking_all_read_needs_a_post(client, author):
    _notification(author)
    client.force_login(author)

    assert _get(client, READ_ALL_URL).status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert Notification.objects.filter(read=False).exists()
