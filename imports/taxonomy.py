from django.core.exceptions import ValidationError

from hashlib import sha256

from django.utils.text import slugify

from exams.models import Subject, Topic


def topic_identity(topic):
    if topic is None:
        return None
    return topic.pk if topic.pk is not None else ["new", topic.subject_id, " ".join(topic.name.split()).casefold()]


def proposed_topic(subject, value):
    name = " ".join(value.split())
    key = name.casefold()
    suffix = sha256(key.encode("utf-8")).hexdigest()[:16]
    topic = Topic(subject=subject, name=name, slug=f"{slugify(name)[:175] or 'topic'}-{suffix}")
    topic.full_clean()
    return topic


def persist_topic(topic, user):
    # Caller holds the subject lock within the import transaction.
    matches = [item for item in Topic.objects.filter(subject_id=topic.subject_id)
               if " ".join(item.name.split()).casefold() == " ".join(topic.name.split()).casefold()]
    if len(matches) > 1:
        raise ValidationError("Topic match is ambiguous. Revalidate the import.")
    if matches:
        return matches[0]
    if not user.has_perm("exams.add_topic"):
        raise ValidationError("Creating a new topic requires the Add topic permission. Map to an existing topic or ask an administrator.")
    topic.save()
    return topic

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
