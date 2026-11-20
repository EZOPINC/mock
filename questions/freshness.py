from django.core.exceptions import ValidationError
from django.utils import timezone


def resolve_freshness_dates(subject, *, current_as_of=None, expires_on=None, default_date=None):
    years = subject.question_freshness_years
    if years is not None and expires_on is None:
        current_as_of = current_as_of or default_date or timezone.localdate()
        try:
            expires_on = current_as_of.replace(year=current_as_of.year + years)
        except ValueError:
            if (current_as_of.month, current_as_of.day) != (2, 29) or current_as_of.year + years > 9999:
                raise ValidationError("This current-as-of date cannot be used to calculate expiry.")
            expires_on = current_as_of.replace(year=current_as_of.year + years, day=28)
    if current_as_of and expires_on and expires_on <= current_as_of:
        raise ValidationError("Expiry must be after the current-as-of date.")
    return current_as_of, expires_on
