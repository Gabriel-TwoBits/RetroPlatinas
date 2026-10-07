"""Comments on games and achievements: shown at the bottom of their pages, added and deleted
through HTMX, deleted only by their author or staff, never reachable on another user's draft."""

from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client

from apps.achievements.models import Achievement
from apps.comments.models import COMMENT_MAX_CHARS, Comment
from apps.games.models import Console, Game

User = get_user_model()

PLAYSTATION_RA_ID = 12
PASSWORD = "pw-secret-123"
UNKNOWN_ID = 999_999
ACHIEVEMENT_POINTS = 5
HTMX = {"HTTP_HX_REQUEST": "true"}
NO_COMMENTS = "No comments yet"
LOGIN_PROMPT = "Log in to comment"
POST_BUTTON = "Post comment"


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
def game(db):
    console = Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


def _achievement(game, author, status=Achievement.STATUS_COMMUNITY):
    return Achievement.objects.create(
        game=game,
        author=author,
        title="Beach",
        description="Clear the beach",
        points=ACHIEVEMENT_POINTS,
        mem_addr="0xH0001=1",
        status=status,
    )


@pytest.fixture
def achievement(game, author):
    return _achievement(game, author)


def _page(client, path):
    response = client.get(path, HTTP_ACCEPT_LANGUAGE="en")
    assert response.status_code == HTTPStatus.OK
    return response.content.decode()


def _game_page(client, game):
    return _page(client, f"/games/{game.pk}/")


def _achievement_page(client, achievement):
    return _page(client, f"/games/{achievement.game_id}/achievements/{achievement.pk}/")


def _game_add_url(game):
    return f"/games/{game.pk}/comments/"


def _achievement_add_url(achievement):
    return f"/games/{achievement.game_id}/achievements/{achievement.pk}/comments/"


def _delete_url(comment):
    return f"/comments/{comment.pk}/delete/"


def _post(client, url, data=None, htmx=True):
    headers = HTMX if htmx else {}
    return client.post(url, data or {}, HTTP_ACCEPT_LANGUAGE="en", **headers)


def _comment(author, target_game=None, target_achievement=None, content="First!"):
    return Comment.objects.create(
        author=author, content=content, game=target_game, achievement=target_achievement
    )


# --- Model ---


@pytest.mark.django_db
@pytest.mark.parametrize("on_game, on_achievement", [(True, True), (False, False)])
def test_a_comment_targets_exactly_one_of_a_game_and_an_achievement(
    author, game, achievement, on_game, on_achievement
):
    with pytest.raises(IntegrityError), transaction.atomic():
        Comment.objects.create(
            author=author,
            content="Both or neither",
            game=game if on_game else None,
            achievement=achievement if on_achievement else None,
        )


@pytest.mark.django_db
def test_deleting_the_target_deletes_its_comments(author, game, achievement):
    _comment(author, target_achievement=achievement)
    _comment(author, target_game=game)
    game.delete()
    assert not Comment.objects.exists()


# --- Game page ---


@pytest.mark.django_db
def test_a_game_comment_is_shown_to_other_users_and_visitors(client, author, other, game):
    _comment(author, target_game=game, content="Great game")
    assert "Great game" in _game_page(client, game)
    client.force_login(other)
    body = _game_page(client, game)
    assert "Great game" in body
    assert "1 comment" in body


@pytest.mark.django_db
def test_game_page_lists_comments_oldest_first(client, author, other, game):
    _comment(author, target_game=game, content="Older comment")
    _comment(other, target_game=game, content="Newer comment")
    body = _game_page(client, game)
    assert body.index("Older comment") < body.index("Newer comment")
    assert "2 comments" in body


@pytest.mark.django_db
def test_game_page_without_comments_says_so(client, game):
    assert NO_COMMENTS in _game_page(client, game)


@pytest.mark.django_db
def test_game_page_shows_only_the_game_comments(client, author, game, achievement):
    _comment(author, target_achievement=achievement, content="About the achievement")
    assert "About the achievement" not in _game_page(client, game)


@pytest.mark.django_db
def test_an_anonymous_visitor_gets_a_login_link_instead_of_the_form(client, game):
    body = _game_page(client, game)
    assert LOGIN_PROMPT in body
    assert f"/login/?next=/games/{game.pk}/%23comments" in body
    assert POST_BUTTON not in body


@pytest.mark.django_db
def test_a_logged_in_user_gets_the_form(client, other, game):
    client.force_login(other)
    body = _game_page(client, game)
    assert POST_BUTTON in body
    assert f'hx-post="{_game_add_url(game)}"' in body
    assert f'maxlength="{COMMENT_MAX_CHARS}"' in body
    assert LOGIN_PROMPT not in body


@pytest.mark.django_db
def test_comment_content_is_escaped(client, author, game):
    _comment(author, target_game=game, content='<script>alert("x")</script>')
    body = _game_page(client, game)
    assert '<script>alert("x")</script>' not in body
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in body


@pytest.mark.django_db
def test_the_delete_button_shows_only_to_the_author_and_staff(client, author, other, staff, game):
    comment = _comment(author, target_game=game)
    delete_form = f'action="{_delete_url(comment)}"'
    assert delete_form not in _game_page(client, game)
    client.force_login(other)
    assert delete_form not in _game_page(client, game)
    client.force_login(author)
    assert delete_form in _game_page(client, game)
    client.force_login(staff)
    assert delete_form in _game_page(client, game)


# --- Adding ---


@pytest.mark.django_db
def test_adding_a_game_comment_answers_the_section_with_it(client, other, game):
    client.force_login(other)
    response = _post(client, _game_add_url(game), {"content": "Hello there"})
    assert response.status_code == HTTPStatus.OK
    body = response.content.decode()
    assert body.lstrip().startswith('<section id="comments"')
    assert "Hello there" in body
    comment = Comment.objects.get()
    assert (comment.author, comment.game, comment.achievement) == (other, game, None)
    assert "Hello there" in _game_page(Client(), game)


@pytest.mark.django_db
def test_adding_a_comment_without_htmx_returns_to_the_page(client, other, game):
    client.force_login(other)
    response = _post(client, _game_add_url(game), {"content": "No script"}, htmx=False)
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == f"/games/{game.pk}/#comments"
    assert Comment.objects.get().content == "No script"


@pytest.mark.django_db
def test_adding_an_achievement_comment_shows_it_on_its_page_only(client, other, game, achievement):
    client.force_login(other)
    response = _post(client, _achievement_add_url(achievement), {"content": "Tricky one"})
    assert response.status_code == HTTPStatus.OK
    assert "Tricky one" in response.content.decode()
    assert Comment.objects.get().achievement == achievement
    assert "Tricky one" in _achievement_page(client, achievement)
    assert "Tricky one" not in _game_page(client, game)


@pytest.mark.django_db
def test_adding_a_comment_requires_login(client, game):
    response = _post(client, _game_add_url(game), {"content": "Anonymous"})
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"].startswith("/login/")
    assert not Comment.objects.exists()


@pytest.mark.django_db
def test_adding_a_comment_rejects_get(client, other, game):
    client.force_login(other)
    response = client.get(_game_add_url(game))
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_adding_a_comment_requires_the_csrf_token(other, game):
    client = Client(enforce_csrf_checks=True)
    client.force_login(other)
    response = _post(client, _game_add_url(game), {"content": "Forged"})
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert not Comment.objects.exists()


@pytest.mark.django_db
def test_adding_a_comment_accepts_the_page_csrf_token(other, game):
    client = Client(enforce_csrf_checks=True)
    client.force_login(other)
    client.get(f"/games/{game.pk}/")
    token = client.cookies["csrftoken"].value
    response = _post(
        client, _game_add_url(game), {"content": "Genuine", "csrfmiddlewaretoken": token}
    )
    assert response.status_code == HTTPStatus.OK
    assert Comment.objects.get().content == "Genuine"


@pytest.mark.django_db
@pytest.mark.parametrize("content", ["", "   \n  ", "x" * (COMMENT_MAX_CHARS + 1)])
def test_an_invalid_comment_answers_the_form_with_its_error(client, other, game, content):
    client.force_login(other)
    response = _post(client, _game_add_url(game), {"content": content})
    assert response.status_code == HTTPStatus.OK
    assert 'id="id_content_error"' in response.content.decode()
    assert not Comment.objects.exists()


@pytest.mark.django_db
def test_a_comment_at_the_limit_counts_a_line_break_as_one_character(client, other, game):
    client.force_login(other)
    head = "x" * (COMMENT_MAX_CHARS - len("\nx"))
    response = _post(client, _game_add_url(game), {"content": f"{head}\r\nx"})
    assert response.status_code == HTTPStatus.OK
    assert Comment.objects.get().content == f"{head}\nx"


@pytest.mark.django_db
def test_adding_a_comment_to_an_unknown_game_is_404(client, other):
    client.force_login(other)
    response = _post(client, f"/games/{UNKNOWN_ID}/comments/", {"content": "Lost"})
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_adding_a_comment_to_an_achievement_of_another_game_is_404(client, other, achievement):
    other_game = Game.objects.create(title="Spyro", console=achievement.game.console)
    client.force_login(other)
    response = _post(
        client,
        f"/games/{other_game.pk}/achievements/{achievement.pk}/comments/",
        {"content": "Wrong game"},
    )
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_comments_on_another_users_draft_do_not_exist(client, author, other, staff, game):
    draft = _achievement(game, author, status=Achievement.STATUS_DRAFT)
    for user in (other, staff):
        client.force_login(user)
        response = _post(client, _achievement_add_url(draft), {"content": "Peek"})
        assert response.status_code == HTTPStatus.NOT_FOUND
    assert not Comment.objects.exists()


@pytest.mark.django_db
def test_the_author_comments_on_their_own_draft(client, author, game):
    draft = _achievement(game, author, status=Achievement.STATUS_DRAFT)
    client.force_login(author)
    response = _post(client, _achievement_add_url(draft), {"content": "Note to self"})
    assert response.status_code == HTTPStatus.OK
    assert "Note to self" in _achievement_page(client, draft)


# --- Deleting ---


@pytest.mark.django_db
def test_deleting_your_own_comment_removes_it(client, author, game):
    comment = _comment(author, target_game=game, content="Regret")
    client.force_login(author)
    response = _post(client, _delete_url(comment))
    assert response.status_code == HTTPStatus.OK
    body = response.content.decode()
    assert "Regret" not in body
    assert NO_COMMENTS in body
    assert not Comment.objects.exists()
    assert "Regret" not in _game_page(client, game)


@pytest.mark.django_db
def test_deleting_without_htmx_returns_to_the_page(client, author, achievement):
    comment = _comment(author, target_achievement=achievement)
    client.force_login(author)
    response = _post(client, _delete_url(comment), htmx=False)
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == (
        f"/games/{achievement.game_id}/achievements/{achievement.pk}/#comments"
    )
    assert not Comment.objects.exists()


@pytest.mark.django_db
def test_deleting_another_users_comment_is_403(client, author, other, game):
    comment = _comment(author, target_game=game)
    client.force_login(other)
    response = _post(client, _delete_url(comment))
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert Comment.objects.filter(pk=comment.pk).exists()


@pytest.mark.django_db
def test_staff_delete_any_comment(client, author, staff, achievement):
    comment = _comment(author, target_achievement=achievement, content="Spam")
    client.force_login(staff)
    response = _post(client, _delete_url(comment))
    assert response.status_code == HTTPStatus.OK
    assert "Spam" not in response.content.decode()
    assert not Comment.objects.exists()


@pytest.mark.django_db
def test_deleting_requires_login(client, author, game):
    comment = _comment(author, target_game=game)
    response = _post(client, _delete_url(comment))
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"].startswith("/login/")
    assert Comment.objects.exists()


@pytest.mark.django_db
def test_deleting_rejects_get(client, author, game):
    comment = _comment(author, target_game=game)
    client.force_login(author)
    assert client.get(_delete_url(comment)).status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert Comment.objects.exists()


@pytest.mark.django_db
def test_deleting_an_unknown_comment_is_404(client, author):
    client.force_login(author)
    response = _post(client, f"/comments/{UNKNOWN_ID}/delete/")
    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_a_comment_on_a_draft_another_user_cannot_see_is_404_to_them(
    client, author, other, staff, game
):
    """A published achievement moved back to draft keeps its comments, out of reach of all but
    the draft's author."""
    achievement = _achievement(game, author)
    comment = _comment(other, target_achievement=achievement)
    achievement.status = Achievement.STATUS_DRAFT
    achievement.save()
    for user in (other, staff):
        client.force_login(user)
        assert _post(client, _delete_url(comment)).status_code == HTTPStatus.NOT_FOUND
    client.force_login(author)
    assert _post(client, _delete_url(comment)).status_code == HTTPStatus.FORBIDDEN
    assert Comment.objects.exists()
