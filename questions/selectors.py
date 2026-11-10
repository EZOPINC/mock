"""Question Bank topic filtering; distinct master IDs, not translation/tag rows."""
from django.core.exceptions import ValidationError

from .models import Question


def questions_by_topics(topic_ids, *, queryset=None):
    ids = list(topic_ids)
    if any(type(pk) is not int or pk <= 0 for pk in ids):
        raise ValidationError("Topic IDs must be positive integers.")
    if queryset is None:
        queryset = Question.objects.all()
    return queryset.filter(topic_associations__topic_id__in=ids).distinct()
