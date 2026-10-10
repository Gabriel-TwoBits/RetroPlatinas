from django import forms
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.achievements.code_notes import MAX_CODE_NOTE_ADDRESS, typed_address
from apps.achievements.editing import settable_points
from apps.achievements.models import (
    BADGE_UPLOAD_FORMATS,
    BYTES_PER_MIB,
    MAX_BADGE_UPLOAD_BYTES,
    MAX_BADGE_UPLOAD_SIDE_PX,
    Achievement,
    CodeNote,
    validate_badge_image,
)
from apps.achievements.triggers import validate_trigger
from apps.games.models import Game, site_set_order

BADGE_UPLOAD_ACCEPT = ",".join(
    f"image/{image_format.lower()}" for image_format in BADGE_UPLOAD_FORMATS
)
FIELDS = ("title", "description", "points", "type", "badge", "mem_addr", "status")
DESCRIPTION_ROWS = 3
MEM_ADDR_ROWS = 4


class AchievementForm(forms.ModelForm):
    """An achievement as its author or staff edits it on the site.

    A new badge upload becomes a `Badge`, which the view names the achievement after.
    """

    points = forms.TypedChoiceField(coerce=int, label=_("Points"))
    badge = forms.FileField(
        required=False,
        validators=[validate_badge_image],
        label=_("New badge"),
        widget=forms.FileInput(attrs={"accept": BADGE_UPLOAD_ACCEPT}),
    )
    # A declared field outside the model would otherwise come last; `set` exists on creation.
    field_order = ("set", *FIELDS)

    class Meta:
        model = Achievement
        fields = FIELDS
        labels = {"mem_addr": _("Condition (mem_addr)")}
        help_texts = {
            "mem_addr": _(
                "The trigger in rcheevos syntax, checked with the same parser the emulators run."
            ),
            "status": _(
                "Every player receives both. An official achievement is awarded and worth points; "
                "an unofficial one sits in the emulator's unofficial list and is never awarded."
            ),
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": DESCRIPTION_ROWS}),
            "mem_addr": forms.Textarea(attrs={"rows": MEM_ADDR_ROWS, "spellcheck": "false"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk is None:
            self.fields["set"] = SetChoiceField(self.instance.game)
            self.order_fields(self.field_order)
        else:
            # An achievement stays in the set it was created in.
            pass
        points = sorted(settable_points(self.instance.points))
        self.fields["points"].choices = [(value, value) for value in points]
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

    def clean_set(self):
        chosen = self.cleaned_data["set"]
        self.instance.game = chosen
        return chosen


class SetChoiceField(forms.ModelChoiceField):
    """The set a new achievement goes into: the core set of `game`'s core game or one of its
    subsets, `game` chosen first."""

    def __init__(self, game):
        core = game.core_game
        super().__init__(
            queryset=Game.objects.filter(Q(pk=core.pk) | Q(parent_game=core)),
            initial=game.pk,
            empty_label=None,
            label=_("Set"),
            help_text=_(
                "The core set holds the game's own 100%; a subset holds challenges players opt "
                "into."
            ),
        )
        self.choices = [
            (choice.pk, self.label_from_instance(choice))
            for choice in sorted(self.queryset, key=site_set_order)
        ]

    def label_from_instance(self, obj):
        if obj.is_subset:
            return _("%(title)s (%(type)s subset)") % {
                "title": obj.set_title,
                "type": obj.get_set_type_display(),
            }
        else:
            return _("Core set")


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
