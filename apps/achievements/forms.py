from django import forms
from django.utils.translation import gettext_lazy as _

from apps.achievements.code_notes import MAX_CODE_NOTE_ADDRESS, typed_address
from apps.achievements.editing import settable_statuses
from apps.achievements.models import (
    ACHIEVEMENT_POINT_VALUES,
    BADGE_UPLOAD_FORMATS,
    BYTES_PER_MIB,
    MAX_BADGE_UPLOAD_BYTES,
    MAX_BADGE_UPLOAD_SIDE_PX,
    Achievement,
    CodeNote,
    validate_badge_image,
)
from apps.achievements.triggers import validate_trigger

BADGE_UPLOAD_ACCEPT = ",".join(
    f"image/{image_format.lower()}" for image_format in BADGE_UPLOAD_FORMATS
)
FIELDS = ("title", "description", "points", "type", "badge", "mem_addr", "status")
DESCRIPTION_ROWS = 3
MEM_ADDR_ROWS = 4


class AchievementForm(forms.ModelForm):
    """An achievement as its author or staff edits it on the site; `editor` is who submits it.

    A new badge upload becomes a `Badge`, which the view names the achievement after.
    """

    points = forms.TypedChoiceField(coerce=int, label=_("Points"))
    badge = forms.FileField(
        required=False,
        validators=[validate_badge_image],
        label=_("New badge"),
        widget=forms.FileInput(attrs={"accept": BADGE_UPLOAD_ACCEPT}),
    )
    # A declared field outside the model would otherwise come last.
    field_order = FIELDS

    class Meta:
        model = Achievement
        fields = FIELDS
        labels = {"mem_addr": _("Condition (mem_addr)")}
        help_texts = {
            "mem_addr": _(
                "The trigger in rcheevos syntax, checked with the same parser the emulators run."
            ),
            "status": _(
                "A draft reaches only its author, in the emulator's unofficial list, and is never "
                "awarded. Community and verified reach every player and are worth points."
            ),
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": DESCRIPTION_ROWS}),
            "mem_addr": forms.Textarea(attrs={"rows": MEM_ADDR_ROWS, "spellcheck": "false"}),
        }

    def __init__(self, *args, editor, **kwargs):
        super().__init__(*args, **kwargs)
        # Points set outside the scale (in the admin) stay selectable while they are unchanged.
        points = sorted(ACHIEVEMENT_POINT_VALUES | {self.instance.points})
        self.fields["points"].choices = [(value, value) for value in points]
        allowed = settable_statuses(editor, self.instance.status)
        self.fields["status"].choices = [
            (status, label) for status, label in Achievement.STATUS_CHOICES if status in allowed
        ]
        self.fields["badge"].help_text = _(
            "PNG, JPEG or GIF, at most %(megabytes)s MiB and %(pixels)s pixels a side. "
            "Leave empty to keep the current badge."
        ) % {
            "megabytes": MAX_BADGE_UPLOAD_BYTES // BYTES_PER_MIB,
            "pixels": MAX_BADGE_UPLOAD_SIDE_PX,
        }

    def clean_mem_addr(self):
        mem_addr = self.cleaned_data["mem_addr"]
        validate_trigger(mem_addr)
        return mem_addr


CODE_NOTE_ROWS = 4
CODE_NOTE_SEARCH_MAX_LENGTH = 100


class CodeNoteSearchForm(forms.Form):
    q = forms.CharField(required=False, max_length=CODE_NOTE_SEARCH_MAX_LENGTH, label=_("Search"))


class CodeNoteForm(forms.Form):
    """A code note's text, as its author or staff changes it."""

    note = forms.CharField(
        label=_("Note"),
        widget=forms.Textarea(attrs={"rows": CODE_NOTE_ROWS}),
        help_text=_("What the address holds: its size, its values and what they mean."),
    )


class NewCodeNoteForm(CodeNoteForm):
    """A new code note: `address` cleans to the number the hex text names."""

    address = forms.CharField(
        label=_("Address"),
        max_length=CodeNote._meta.get_field("address").max_length,
        help_text=_("In hexadecimal, such as 0x001234."),
        widget=forms.TextInput(attrs={"spellcheck": "false", "autocomplete": "off"}),
    )
    field_order = ("address", "note")

    def clean_address(self):
        address = typed_address(self.cleaned_data["address"])
        if address is None:
            raise forms.ValidationError(
                _("Enter a hexadecimal address from 0x0 to 0x%(max)x, such as 0x001234."),
                params={"max": MAX_CODE_NOTE_ADDRESS},
            )
        else:
            return address
