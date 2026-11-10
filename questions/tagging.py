"""Transactional topic writes. PostgreSQL synchronizes the legacy primary pointer.

No signals: all writers lock the Question first; deferred database guards verify
the final relation/pointer state. Revision content and workflow fields are untouched.
"""
from django.core.exceptions import ValidationError
from django.db import models, transaction

from exams.models import Topic
from .models import Question, QuestionTopic


def _tags():
    # Private, unguarded queryset used only inside these validated transactions.
    return models.QuerySet(model=QuestionTopic)


@transaction.atomic
def set_question_topics(question, topic_ids, *, primary_topic_id=None):
    question_id = getattr(question, "pk", question)
    current = Question.objects.select_for_update().get(pk=question_id)
    ids = list(topic_ids)
    if primary_topic_id is not None and (type(primary_topic_id) is not int or primary_topic_id <= 0):
        raise ValidationError("Primary topic ID must be a positive integer.")
    if any(type(pk) is not int or pk <= 0 for pk in ids) or len(ids) != len(set(ids)):
        raise ValidationError("Topic IDs must be distinct positive integers.")
    if ids and primary_topic_id not in ids:
        raise ValidationError("Select exactly one primary topic from the assigned topics.")
    if not ids and primary_topic_id is not None:
        raise ValidationError("An unclassified question cannot have a primary topic.")
    topics = list(Topic.objects.filter(pk__in=ids))
    if len(topics) != len(ids) or any(topic.subject_id != current.subject_id for topic in topics):
        raise ValidationError("Every topic must exist and belong to the question's subject.")
    # One database boundary also covers legacy Question.save(), imports and SQL writes.
    models.QuerySet(model=Question).filter(pk=current.pk).update(topic_id=primary_topic_id)
    _tags().filter(question_id=current.pk).exclude(topic_id__in=ids).delete()
    if primary_topic_id is not None:
        _tags().filter(question_id=current.pk).exclude(topic_id=primary_topic_id).update(is_primary=False)
        primary, _ = _tags().get_or_create(question_id=current.pk, topic_id=primary_topic_id, defaults={"is_primary": True})
        _tags().filter(pk=primary.pk).update(is_primary=True)
    for pk in ids:
        _tags().get_or_create(question_id=current.pk, topic_id=pk, defaults={"is_primary": pk == primary_topic_id})
    current.refresh_from_db()
    if isinstance(question, Question):
        question.topic_id = current.topic_id
        question._state.fields_cache.pop("topic", None)
        question.__dict__.pop("_prefetched_objects_cache", None)
    return current


@transaction.atomic
def save_tag(tag, *args, **kwargs):
    parent = Question.objects.select_for_update().get(pk=tag.question_id)
    tag.question = parent
    tag.full_clean()
    if not tag.is_primary and not QuestionTopic.objects.filter(question=parent, is_primary=True).exclude(pk=tag.pk).exists():
        raise ValidationError("A classified question needs one primary topic.")
    result = models.Model.save(tag, *args, **kwargs)
    primary = QuestionTopic.objects.get(question=parent, is_primary=True)
    if parent.topic_id != primary.topic_id:
        models.QuerySet(model=Question).filter(pk=parent.pk).update(topic_id=primary.topic_id)
    return result


@transaction.atomic
def delete_tag(tag, *args, **kwargs):
    parent = Question.objects.select_for_update().get(pk=tag.question_id)
    stored = QuestionTopic.objects.get(pk=tag.pk, question=parent)
    if stored.is_primary:
        if QuestionTopic.objects.filter(question=parent).exclude(pk=stored.pk).exists():
            raise ValidationError("Choose another primary topic before removing this tag.")
        models.QuerySet(model=Question).filter(pk=parent.pk).update(topic_id=None)
        result = (1, {QuestionTopic._meta.label: 1})
    else:
        result = _tags().filter(pk=stored.pk).delete()
    tag.pk = None
    return result
