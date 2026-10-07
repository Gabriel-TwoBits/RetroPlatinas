"""Code notes as RAIntegration and the site read and write them.

The address column is free text (the admin types it too), so every reader parses it as hex.
"""

import logging

from django.db import transaction

from apps.achievements.editing import can_edit
from apps.achievements.models import CodeNote
from apps.games.models import Game

logger = logging.getLogger(__name__)

HEX_BASE = 16
# RA serves code note addresses as `0x%06x`.
CODE_NOTE_ADDRESS_HEX_DIGITS = 6


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


def code_notes_by_address(game):
    """The game's notes by address; the text column holds hex addresses in any padding.

    A note whose address does not parse is left out rather than failing the whole game.
    """
    # TRADEOFF: parsed in Python because `address` is text; an integer column makes it a query.
    notes = CodeNote.objects.filter(game=game).select_related("author").order_by("id")
    by_address = {}
    for note in notes:
        address = parsed_address(note)
        if address is not None:
            by_address[address] = note
        else:
            continue
    return by_address


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
                # As on RA, a note is credited to whoever wrote its current text.
                note.author = user
                note.note = text
                note.save(update_fields=["author", "note", "updated_at"])
                successful.append(address)
    return successful, denied
