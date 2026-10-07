"""Code notes as RAIntegration and the site read and write them.

The address column is free text (the admin types it too), so every reader parses it as hex.
"""

import logging
import re

from django.db import transaction

from apps.achievements.editing import can_edit
from apps.achievements.models import CodeNote
from apps.games.models import Game

logger = logging.getLogger(__name__)

HEX_BASE = 16
# RA serves code note addresses as `0x%06x`.
CODE_NOTE_ADDRESS_HEX_DIGITS = 6
# rcheevos sends and reads a code note address as a uint32.
MAX_CODE_NOTE_ADDRESS = 0xFFFFFFFF
TYPED_ADDRESS = re.compile(r"(?:0x)?([0-9a-f]+)", re.IGNORECASE)


def served_address(address):
    """The address as RA serves it, which rcheevos reads back as hex."""
    return f"0x{address:0{CODE_NOTE_ADDRESS_HEX_DIGITS}x}"


def stored_address(address):
    return f"0x{address:x}"


def parsed_address(note):
    """The note's address as a number, else `None`: the column is free text, typed in the admin."""
    try:
        address = int(note.address, HEX_BASE)
    except ValueError:
        address = None
    if address is None or address < 0:
        logger.warning("Code note %s has no hex address: %r", note.pk, note.address)
        return None
    else:
        return address


def address_label(note):
    """The note's address as served, else as stored when it does not parse."""
    address = parsed_address(note)
    if address is None:
        return note.address
    else:
        return served_address(address)


def typed_address(text):
    """The address a person typed as hex, `0x` optional, else `None`."""
    match = TYPED_ADDRESS.fullmatch(text)
    if match is None:
        return None
    address = int(match.group(1), HEX_BASE)
    if address > MAX_CODE_NOTE_ADDRESS:
        return None
    else:
        return address


def code_notes_by_address(game):
    """The game's notes by address; the text column holds hex addresses in any padding.

    A note whose address does not parse is left out rather than failing the whole game.
    """
    # TRADEOFF: parsed in Python because `address` is text; an integer column makes it a query.
    notes = CodeNote.objects.filter(game=game).select_related("author", "updated_by").order_by("id")
    by_address = {}
    for note in notes:
        address = parsed_address(note)
        if address is not None:
            by_address[address] = note
        else:
            continue
    return by_address


def search_code_notes(game, query):
    """The game's notes as `(address, note)` in address order, narrowed to those whose text or
    served address contains `query`, or whose address is `query` read as hex."""
    notes = sorted(code_notes_by_address(game).items())
    if query == "":
        return notes
    else:
        needle = query.casefold()
        wanted = typed_address(query)
        return [
            (address, note)
            for address, note in notes
            if address == wanted
            or needle in served_address(address)
            or needle in note.note.casefold()
        ]


def add_code_note(author, game, address, text):
    """Creates `author`'s note at `address`, else `None` when the game has a note there."""
    with transaction.atomic():
        # Serializes writers per game, as `save_code_notes` does.
        Game.objects.select_for_update().get(pk=game.pk)
        if address in code_notes_by_address(game):
            return None
        else:
            return CodeNote.objects.create(
                game=game, author=author, address=stored_address(address), note=text
            )


def _compared_text(text):
    """The text as two writers' copies are compared: browsers send a textarea's line breaks as
    CRLF and Django strips its ends, so neither difference is an edit."""
    return text.replace("\r\n", "\n").strip()


def rewrite_code_note(note, editor, text):
    """Replaces the note's text as `editor` writes it; the note stays its author's.

    The same text again is no edit: who last changed the note stays as it was.
    """
    if _compared_text(text) == _compared_text(note.note):
        return
    else:
        note.note = text
        note.updated_by = editor
        note.save(update_fields=["note", "updated_by", "updated_at"])


def save_code_notes(user, game, notes):
    """Writes `{address: text}`, an empty text deleting the note, as far as `user` may.

    Returns the addresses written and the addresses refused: anyone may add a note, only its
    author or staff may change or delete it.
    """
    successful = []
    denied = []
    with transaction.atomic():
        # Serializes writers per game, so two adds of one new address cannot both insert it.
        Game.objects.select_for_update().get(pk=game.pk)
        existing = code_notes_by_address(game)
        for address, text in notes.items():
            note = existing.get(address)
            if note is None and text == "":
                successful.append(address)
            elif note is None:
                CodeNote.objects.create(
                    game=game, author=user, address=stored_address(address), note=text
                )
                successful.append(address)
            elif not can_edit(user, note.author_id):
                denied.append(address)
            elif text == "":
                note.delete()
                successful.append(address)
            else:
                rewrite_code_note(note, user, text)
                successful.append(address)
    return successful, denied
