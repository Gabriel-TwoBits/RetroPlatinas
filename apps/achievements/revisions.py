"""An achievement's revision history: what each change did, and reverting to an earlier state."""

import difflib
import re
from dataclasses import dataclass

from django.db import transaction

from apps.achievements.editing import can_edit, settable_points
from apps.achievements.models import REVISED_FIELDS, AchievementRevision
from apps.achievements.scoring import SCORED_FIELDS, recalculate_unlocker_points

CONDITION_SEPARATOR = "_"
# An alt group starts at an `S` (or `s`) that ends a condition; after `0x` it is the bit-6 size.
ALT_GROUP_START = re.compile(r"(?<!0[xX])(?=[sS])")
# ndiff line prefixes; each line's two-character prefix is dropped, and `?` hint lines too.
DIFF_REMOVED = "-"
DIFF_ADDED = "+"
DIFF_KEPT = " "
DIFF_PREFIX_LENGTH = 2
CHOICE_FIELDS = frozenset({"status", "type"})


@dataclass(frozen=True)
class FieldChange:
    label: str
    # `(kind, text)` pairs, `kind` being "removed", "added" or "kept".
    lines: list


@dataclass(frozen=True)
class HistoryEntry:
    number: int
    revision: AchievementRevision
    changes: list
    is_current: bool
    revertible: bool


def _mem_addr_lines(mem_addr):
    """One condition per line, an alt group starting a new one, so a diff names the condition."""
    lines = []
    for group in ALT_GROUP_START.split(mem_addr):
        lines.extend(group.split(CONDITION_SEPARATOR))
    return lines


def _lines(revision, field):
    if revision is None:
        return []
    elif field == "mem_addr":
        return _mem_addr_lines(revision.mem_addr)
    elif field in CHOICE_FIELDS:
        return [str(getattr(revision, f"get_{field}_display")())]
    else:
        return str(getattr(revision, field)).splitlines()


def _diff_lines(old, new):
    lines = []
    for line in difflib.ndiff(old, new):
        prefix, text = line[0], line[DIFF_PREFIX_LENGTH:]
        if prefix == DIFF_REMOVED:
            lines.append(("removed", text))
        elif prefix == DIFF_ADDED:
            lines.append(("added", text))
        elif prefix == DIFF_KEPT:
            lines.append(("kept", text))
        else:
            # A `?` line marks characters within the line above; the coloured lines say enough.
            pass
    return lines


def changes_between(previous, revision):
    """The fields `revision` changed from `previous`, every field for the first revision."""
    meta = AchievementRevision._meta
    changes = []
    for field in REVISED_FIELDS:
        old, new = _lines(previous, field), _lines(revision, field)
        if old != new:
            label = meta.get_field(field).verbose_name
            changes.append(FieldChange(label=label, lines=_diff_lines(old, new)))
        else:
            # An unchanged field is left out.
            pass
    return changes


def can_revert(user, achievement, revision):
    """Its author or staff may revert to a revision whose points they may also set in the editor:
    nobody restores points off RA's scale."""
    return can_edit(user, achievement.author_id) and revision.points in settable_points(
        achievement.points
    )


def history(achievement, user):
    """The achievement's revisions, newest first, each with what it changed."""
    # TRADEOFF: every revision on one page; paginate if an achievement reaches hundreds.
    revisions = list(achievement.revisions.select_related("editor"))
    current = achievement.revised_values()
    latest_number = len(revisions)
    entries = []
    previous = None
    for number, revision in enumerate(revisions, start=1):
        # A revert repeats an earlier revision's values, so only the latest one is current.
        holds_current = revision.revised_values() == current
        entries.append(
            HistoryEntry(
                number=number,
                revision=revision,
                changes=changes_between(previous, revision),
                is_current=holds_current and number == latest_number,
                revertible=not holds_current and can_revert(user, achievement, revision),
            )
        )
        previous = revision
    entries.reverse()
    return entries


def revert(achievement, revision, editor):
    """Gives `achievement` the fields `revision` recorded, as a new revision by `editor`, and
    recounts its unlockers' points when its status or points change."""
    with transaction.atomic():
        restored = revision.revised_values()
        changed = {
            field for field, value in restored.items() if getattr(achievement, field) != value
        }
        for field, value in restored.items():
            setattr(achievement, field, value)
        achievement.save(editor=editor)
        if SCORED_FIELDS & changed:
            recalculate_unlocker_points([achievement.pk])
        else:
            # Its unlockers' totals do not depend on what changed.
            pass
    return achievement
