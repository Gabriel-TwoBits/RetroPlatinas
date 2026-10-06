from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import BIO_MAX_LENGTH, User


class RegistrationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("A user with that email already exists."))
        return email


class MultilineCharField(forms.CharField):
    """Browsers submit textarea line breaks as CRLF but count them as one character against
    `maxlength`; normalising to LF keeps the server's length check in step with the browser."""

    def to_python(self, value):
        return super().to_python(value).replace("\r\n", "\n")


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("bio",)
        field_classes = {"bio": MultilineCharField}
        widgets = {"bio": forms.Textarea}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bio"].help_text = _("Shown on your profile, up to %(limit)s characters.") % {
            "limit": BIO_MAX_LENGTH
        }
