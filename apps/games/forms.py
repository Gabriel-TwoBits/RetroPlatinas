from django import forms
from django.utils.translation import gettext_lazy as _

from apps.games.models import Console, Game

ORDER_TITLE = "title"
ORDER_ACHIEVEMENTS = "achievements"
ORDER_PLAYERS = "players"
# The first is the default: a select with nothing chosen shows its first option.
ORDERINGS = [
    (ORDER_TITLE, _("Alphabetical")),
    (ORDER_ACHIEVEMENTS, _("Most achievements")),
    (ORDER_PLAYERS, _("Most players")),
]
DEFAULT_ORDER = ORDER_TITLE
# A game without an official achievement has no set to play, so it is listed only on request.
DEFAULT_MIN_ACHIEVEMENTS = 1
TITLE_SEARCH_MAX_LENGTH = Game._meta.get_field("title").max_length


class GameFilterForm(forms.Form):
    """The games list's query string; a missing or blank field takes its default."""

    q = forms.CharField(required=False, max_length=TITLE_SEARCH_MAX_LENGTH, label=_("Title"))
    console = forms.ModelChoiceField(
        queryset=Console.objects.all(),
        required=False,
        empty_label=_("All consoles"),
        label=_("Console"),
    )
    min_achievements = forms.IntegerField(
        required=False, min_value=0, label=_("Minimum achievements")
    )
    order = forms.ChoiceField(choices=ORDERINGS, required=False, label=_("Order by"))

    def clean_min_achievements(self):
        minimum = self.cleaned_data["min_achievements"]
        if minimum is None:
            return DEFAULT_MIN_ACHIEVEMENTS
        else:
            return minimum

    def clean_order(self):
        return self.cleaned_data["order"] or DEFAULT_ORDER


GAME_TITLE_MAX_LENGTH = Game._meta.get_field("title").max_length
# RA's naming for a subset's game: "Crash Bandicoot [Subset - Bonus]".
SUBSET_GAME_TITLE = "{parent} [Subset - {set_title}]"
DESCRIPTION_ROWS = 3


class NewSubsetForm(forms.ModelForm):
    """A new subset of the core game `parent`, on its console and titled after it."""

    class Meta:
        model = Game
        fields = ("set_type", "set_title", "description")
        widgets = {"description": forms.Textarea(attrs={"rows": DESCRIPTION_ROWS})}

    def __init__(self, *args, parent, **kwargs):
        super().__init__(*args, **kwargs)
        # The model's blank choices are for core games; a subset has a type and a title.
        self.fields["set_type"].required = True
        self.fields["set_title"].required = True
        self.instance.parent_game = parent
        self.instance.console_id = parent.console_id

    def clean(self):
        cleaned_data = super().clean()
        set_title = cleaned_data.get("set_title")
        if set_title:
            title = SUBSET_GAME_TITLE.format(
                parent=self.instance.parent_game.title, set_title=set_title
            )
            if len(title) > GAME_TITLE_MAX_LENGTH:
                self.add_error(
                    "set_title",
                    _(
                        "Too long: the subset's game title, the game's title with this one, "
                        "can have at most %(max)s characters."
                    )
                    % {"max": GAME_TITLE_MAX_LENGTH},
                )
            else:
                self.instance.title = title
        else:
            # The required field already reported the missing title.
            pass
        return cleaned_data
