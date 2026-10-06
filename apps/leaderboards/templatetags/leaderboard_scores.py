from django import template

from apps.leaderboards.formatting import format_score

register = template.Library()


@register.filter
def leaderboard_score(score, format_name):
    """`{{ score|leaderboard_score:format }}`: the score as the emulator shows it."""
    return format_score(score, format_name)
