from django.core.exceptions import ValidationError

from exams.models import Subject

UNIDENTIFIED_NAME = "UnIdentified"
UNIDENTIFIED_CODE = "UNIDENTIFIED"
UNIDENTIFIED_SLUG = "unidentified"


def unidentified_subject(subjects):
    """Resolve without writing: unsaved fallback is materialized at confirmation."""
    canonical = next((subject for subject in subjects if subject.code == UNIDENTIFIED_CODE), None)
    if canonical:
        if canonical.name.strip().casefold() != UNIDENTIFIED_NAME.casefold():
            raise ValidationError("The reserved UNIDENTIFIED code belongs to another subject. Resolve this in Subject Admin.")
        return canonical
    matches = [subject for subject in subjects if subject.name.strip().casefold() == UNIDENTIFIED_NAME.casefold()]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValidationError("Multiple UnIdentified subjects exist. Select an explicit subject mapping.")
    subject = Subject(name=UNIDENTIFIED_NAME, code=UNIDENTIFIED_CODE, slug=UNIDENTIFIED_SLUG)
    subject.full_clean()
    return subject


def persist_unidentified(user):
    subject = unidentified_subject(list(Subject.objects.all()))
    if subject.pk:
        return subject
    if not user.has_perm("exams.add_subject"):
        raise ValidationError("Creating UnIdentified requires the Add subject permission. Ask an administrator to create it once, or map to an existing subject.")
    subject, _ = Subject.objects.get_or_create(code=UNIDENTIFIED_CODE, defaults={"name": UNIDENTIFIED_NAME, "slug": UNIDENTIFIED_SLUG})
    if subject.name.strip().casefold() != UNIDENTIFIED_NAME.casefold():
        raise ValidationError("The UNIDENTIFIED subject code is already used by another subject.")
    subject.full_clean()
    return subject
