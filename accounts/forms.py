from django.contrib.auth.forms import UserCreationForm
from .models import User


class RegistrationForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        presentation = {
            "username": ("Choose a username", "Your unique username", "section-register username"),
            "email": ("Email address (optional)", "Your email address", "section-register email"),
            "password1": ("Create a password", "Create a secure password", "section-register new-password"),
            "password2": ("Confirm your password", "Enter your password again", "section-register new-password"),
        }
        for name, (label, placeholder, autocomplete) in presentation.items():
            self.fields[name].label = label
            self.fields[name].widget.attrs.update(placeholder=placeholder, autocomplete=autocomplete)
        self.fields["username"].help_text = "Pick a username you will use to sign in."
        self.fields["username"].widget.attrs.update(autocapitalize="none", spellcheck="false")
        self.fields["password2"].help_text = "Enter the same password to confirm it."

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")
