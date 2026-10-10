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
