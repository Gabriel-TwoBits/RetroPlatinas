"""The code notes pages: the public list and its search, and adding, editing and deleting a note
under the same author-or-staff rule RAIntegration's submitcodenote(s) follows."""

from http import HTTPStatus

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.achievements.code_notes import MAX_CODE_NOTE_ADDRESS
from apps.achievements.forms import CODE_NOTE_SEARCH_MAX_LENGTH
from apps.achievements.models import CodeNote
from apps.games.models import Console, Game

User = get_user_model()

PLAYSTATION_RA_ID = 12
PASSWORD = "pw-secret-123"
AUTHOR = "author"
OTHER = "other"
STAFF = "staff"
UNKNOWN_ID = 999_999
LIVES_NOTE = "Lives (1 byte)"


@pytest.fixture
def game(db):
    console = Console.objects.create(ra_id=PLAYSTATION_RA_ID, name="PlayStation", short_name="PS1")
    return Game.objects.create(title="Crash Bandicoot", console=console)


@pytest.fixture
def author(db):
    return User.objects.create_user(username=AUTHOR, password=PASSWORD)


@pytest.fixture
def other(db):
    return User.objects.create_user(username=OTHER, password=PASSWORD)


@pytest.fixture
def staff(db):
    return User.objects.create_user(username=STAFF, password=PASSWORD, is_staff=True)


@pytest.fixture
def lives(game, author):
    return CodeNote.objects.create(game=game, author=author, address="0x1234", note=LIVES_NOTE)


def _list_url(game):
    return reverse("code_notes", args=[game.pk])


def _new_url(game):
    return reverse("code_note_new", args=[game.pk])


def _edit_url(note):
    return reverse("code_note_edit", args=[note.game_id, note.pk])


def _delete_url(note):
    return reverse("code_note_delete", args=[note.game_id, note.pk])


def _listed(response):
    return [row["note"].pk for row in response.context["rows"]]


# --- List and search ---


@pytest.mark.django_db
def test_list_shows_every_note_in_address_order_to_anyone(client, game, author, other):
    overworld = CodeNote.objects.create(
        game=game, author=other, address="0x61994", note="Overworld status"
    )
    lives = CodeNote.objects.create(game=game, author=author, address="0x001234", note="Lives")

    response = client.get(_list_url(game))

    assert response.status_code == HTTPStatus.OK
    assert _listed(response) == [lives.pk, overworld.pk]
    assert [row["address"] for row in response.context["rows"]] == ["0x001234", "0x061994"]
    assert not any(row["editable"] for row in response.context["rows"])
    assert b"Overworld status" in response.content
    assert _new_url(game).encode() not in response.content


@pytest.mark.django_db
def test_list_marks_only_the_viewers_notes_editable(client, game, author, other, lives):
    theirs = CodeNote.objects.create(game=game, author=other, address="0x10", note="Theirs")
    client.force_login(author)

    response = client.get(_list_url(game))

    editable = {row["note"].pk: row["editable"] for row in response.context["rows"]}
    assert editable == {lives.pk: True, theirs.pk: False}
    assert _edit_url(lives).encode() in response.content
    assert _edit_url(theirs).encode() not in response.content
    assert _new_url(game).encode() in response.content


@pytest.mark.django_db
def test_list_marks_every_note_editable_for_staff(client, staff, lives):
    client.force_login(staff)

    response = client.get(_list_url(lives.game))

    assert [row["editable"] for row in response.context["rows"]] == [True]


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["lives", "0x1234", "0X001234", "1234", "00123"])
def test_search_matches_the_text_or_the_address(client, game, author, lives, query):
    CodeNote.objects.create(game=game, author=author, address="0x61994", note="Overworld")

    response = client.get(_list_url(game), {"q": query})

    assert _listed(response) == [lives.pk]


@pytest.mark.django_db
def test_search_without_a_match_lists_nothing(client, lives):
    response = client.get(_list_url(lives.game), {"q": "health"})

    assert response.status_code == HTTPStatus.OK
    assert _listed(response) == []


@pytest.mark.django_db
def test_search_past_its_length_is_a_bad_request(client, game):
    query = "x" * (CODE_NOTE_SEARCH_MAX_LENGTH + 1)

    assert client.get(_list_url(game), {"q": query}).status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_list_of_an_unknown_game_is_not_found(client, game):
    response = client.get(reverse("code_notes", args=[UNKNOWN_ID]))

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_game_page_links_to_its_code_notes(client, game):
    response = client.get(reverse("game_detail", args=[game.pk]))

    assert _list_url(game).encode() in response.content


# --- Adding ---


@pytest.mark.django_db
def test_add_stores_the_note_normalised_and_another_user_sees_it(client, game, author, other):
    client.force_login(author)

    response = client.post(_new_url(game), {"address": "0x001234", "note": LIVES_NOTE})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == _list_url(game)
    note = CodeNote.objects.get()
    assert (note.game, note.author, note.address, note.note) == (game, author, "0x1234", LIVES_NOTE)
    assert note.updated_by is None
    client.force_login(other)
    listed = client.get(_list_url(game))
    assert _listed(listed) == [note.pk]
    assert LIVES_NOTE.encode() in listed.content


@pytest.mark.django_db
def test_add_reaches_raintegration(client, game, author):
    client.force_login(author)
    client.post(_new_url(game), {"address": "61994", "note": "Overworld"})

    served = client.post(reverse("dorequest"), {"r": "codenotes2", "g": game.pk}).json()

    assert served["CodeNotes"] == [{"User": AUTHOR, "Address": "0x061994", "Note": "Overworld"}]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "address", ["xyz", "0x", "-0x10", "0x1_000", f"{MAX_CODE_NOTE_ADDRESS + 1:x}"]
)
def test_add_rejects_an_address_that_is_not_hex(client, game, author, address):
    client.force_login(author)

    response = client.post(_new_url(game), {"address": address, "note": LIVES_NOTE})

    assert response.status_code == HTTPStatus.OK
    assert "address" in response.context["form"].errors
    assert not CodeNote.objects.exists()


@pytest.mark.django_db
def test_add_refuses_an_address_that_has_a_note(client, game, other, lives):
    client.force_login(other)

    response = client.post(_new_url(game), {"address": "0x001234", "note": "Health"})

    assert response.status_code == HTTPStatus.OK
    assert "address" in response.context["form"].errors
    assert list(CodeNote.objects.values_list("note", flat=True)) == [LIVES_NOTE]


@pytest.mark.django_db
def test_add_requires_a_note(client, game, author):
    client.force_login(author)

    response = client.post(_new_url(game), {"address": "0x1234", "note": ""})

    assert "note" in response.context["form"].errors
    assert not CodeNote.objects.exists()


@pytest.mark.django_db
def test_add_requires_login(client, game):
    response = client.post(_new_url(game), {"address": "0x1234", "note": LIVES_NOTE})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"].startswith(reverse("login"))
    assert not CodeNote.objects.exists()


@pytest.mark.django_db
def test_add_to_an_unknown_game_is_not_found(client, author):
    client.force_login(author)

    response = client.get(reverse("code_note_new", args=[UNKNOWN_ID]))

    assert response.status_code == HTTPStatus.NOT_FOUND


# --- Editing and deleting ---


@pytest.mark.django_db
def test_author_edits_their_note(client, author, lives):
    client.force_login(author)

    form = client.get(_edit_url(lives))
    response = client.post(_edit_url(lives), {"note": "Lives (8-bit)"})

    assert form.status_code == HTTPStatus.OK
    assert form.context["address"] == "0x001234"
    assert response.status_code == HTTPStatus.FOUND
    lives.refresh_from_db()
    assert (lives.note, lives.author, lives.updated_by) == ("Lives (8-bit)", author, author)


@pytest.mark.django_db
def test_saving_the_same_text_records_no_edit(client, author, lives):
    client.force_login(author)

    client.post(_edit_url(lives), {"note": LIVES_NOTE})

    lives.refresh_from_db()
    assert lives.updated_by is None


@pytest.mark.django_db
def test_saving_a_multi_line_note_untouched_records_no_edit(client, author, lives):
    lives.note = "Lives\n0 = game over"
    lives.save()
    client.force_login(author)

    # Browsers send a textarea's line breaks as CRLF.
    client.post(_edit_url(lives), {"note": "Lives\r\n0 = game over\r\n"})

    lives.refresh_from_db()
    assert (lives.note, lives.updated_by) == ("Lives\n0 = game over", None)


@pytest.mark.django_db
def test_edit_requires_a_note(client, author, lives):
    client.force_login(author)

    response = client.post(_edit_url(lives), {"note": ""})

    assert "note" in response.context["form"].errors
    lives.refresh_from_db()
    assert lives.note == LIVES_NOTE


@pytest.mark.django_db
def test_another_user_cannot_edit_or_delete_a_note(client, other, lives):
    client.force_login(other)

    assert client.get(_edit_url(lives)).status_code == HTTPStatus.FORBIDDEN
    assert client.post(_edit_url(lives), {"note": "Mine"}).status_code == HTTPStatus.FORBIDDEN
    assert client.post(_delete_url(lives)).status_code == HTTPStatus.FORBIDDEN
    lives.refresh_from_db()
    assert (lives.note, lives.updated_by) == (LIVES_NOTE, None)


@pytest.mark.django_db
def test_staff_edits_any_note_and_the_list_credits_them(client, author, staff, lives):
    client.force_login(staff)

    response = client.post(_edit_url(lives), {"note": "Lives (8-bit)"})

    assert response.status_code == HTTPStatus.FOUND
    lives.refresh_from_db()
    assert (lives.note, lives.author, lives.updated_by) == ("Lives (8-bit)", author, staff)
    listed = client.get(_list_url(lives.game))
    assert listed.context["rows"][0]["note"].updated_by == staff
    assert reverse("user_detail", args=[STAFF]).encode() in listed.content


@pytest.mark.django_db
def test_staff_deletes_any_note(client, staff, lives):
    client.force_login(staff)

    response = client.post(_delete_url(lives))

    assert response.status_code == HTTPStatus.FOUND
    assert not CodeNote.objects.exists()


@pytest.mark.django_db
def test_author_deletes_their_note(client, author, lives):
    client.force_login(author)

    response = client.post(_delete_url(lives))

    assert response["Location"] == _list_url(lives.game)
    assert not CodeNote.objects.exists()


@pytest.mark.django_db
def test_delete_is_post_only(client, author, lives):
    client.force_login(author)

    assert client.get(_delete_url(lives)).status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert CodeNote.objects.exists()


@pytest.mark.django_db
def test_edit_requires_login(client, lives):
    response = client.post(_edit_url(lives), {"note": "Mine"})

    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"].startswith(reverse("login"))


@pytest.mark.django_db
def test_a_note_under_another_game_is_not_found(client, author, lives):
    console = lives.game.console
    elsewhere = Game.objects.create(title="Crash Bandicoot 2", console=console)
    client.force_login(author)

    url = reverse("code_note_edit", args=[elsewhere.pk, lives.pk])

    assert client.get(url).status_code == HTTPStatus.NOT_FOUND
