from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.forms import MultilineCharField
from apps.comments.models import Comment

CONTENT_ROWS = 3


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ("content",)
        field_classes = {"content": MultilineCharField}
        labels = {"content": _("Your comment")}
        widgets = {"content": forms.Textarea(attrs={"rows": CONTENT_ROWS})}
