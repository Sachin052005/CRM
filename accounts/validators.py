import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

class ComplexityValidator:
    """
    Validates that a password satisfies strong security rules:
    - Minimum length of 8 characters (preferring 10)
    - At least one uppercase letter (A-Z)
    - At least one lowercase letter (a-z)
    - At least one numeric digit (0-9)
    - At least one special character (!@#$%^&*()_+-=[]{}|;:,.<>?)
    - Not matching username or email
    """
    def __init__(self, min_length=8):
        self.min_length = min_length

    def validate(self, password, user=None):
        errors = []

        if len(password) < self.min_length:
            errors.append(_(f"Password must be at least {self.min_length} characters long."))

        if not re.search(r'[A-Z]', password):
            errors.append(_("Password must contain at least one uppercase letter (A-Z)."))

        if not re.search(r'[a-z]', password):
            errors.append(_("Password must contain at least one lowercase letter (a-z)."))

        if not re.search(r'[0-9]', password):
            errors.append(_("Password must contain at least one numeric digit (0-9)."))

        if not re.search(r'[!@#$%^&*()_+\-=\[\]{}|;:,.<>?/~`"\']', password):
            errors.append(_("Password must contain at least one special character (e.g. !@#$%^&*)."))

        if user:
            username = getattr(user, 'username', '')
            email = getattr(user, 'email', '')
            pwd_lower = password.lower()

            if username and username.lower() in pwd_lower:
                errors.append(_("Password cannot contain your username."))
            if email:
                email_local = email.split('@')[0].lower()
                if email_local and email_local in pwd_lower:
                    errors.append(_("Password cannot contain your email prefix."))

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        return _(
            f"Your password must be at least {self.min_length} characters long and contain "
            "at least one uppercase letter, one lowercase letter, one number, and one special character."
        )
