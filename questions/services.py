"""The write boundary for question revisions, review, and publication.

Every transition locks the parent Question first. Review applies to its working
revision; a new revision resets review without replacing the live pointer.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone

from .models import Question, QuestionRevision


def _locked(question):
    return Question.objects.select_for_update().get(pk=question.pk if isinstance(question, Question) else question)


def _check_expected(question, revision_id):
    if revision_id is not None and question.current_revision_id != revision_id:
        raise ValidationError("The working revision changed. Reload and review it before continuing.")


@transaction.atomic
def create_question(*, subject, revision, topic=None, source_question_id=None):
    question = Question.objects.create(subject=subject, topic=topic, source_question_id=source_question_id)
    create_revision(question, **revision)
    question.refresh_from_db()
    return question


@transaction.atomic
def create_revision(question, **content):
    question = _locked(question)
    allowed = {"language", "question_text", "option_a", "option_b", "option_c", "option_d", "correct_answer", "explanation"}
    if set(content) - allowed:
        raise ValidationError("Only revision content fields may be supplied.")
    number = (question.revisions.aggregate(number=Max("revision_number"))["number"] or 0) + 1
    revision = QuestionRevision.objects.create(question=question, revision_number=number, **content)
    question.current_revision = revision
    question.review_status = Question.ReviewStatus.PENDING
    question.save(_workflow=True)
    return revision


@transaction.atomic
def mark_reviewed(question, *, revision_id=None):
    question = _locked(question)
    _check_expected(question, revision_id)
    if not question.current_revision_id:
        raise ValidationError("A valid current revision is required for review.")
    question.current_revision.full_clean()
    question.review_status = Question.ReviewStatus.REVIEWED
    question.save(_workflow=True)
    return question


@transaction.atomic
def publish_question(question, *, revision_id=None):
    question = _locked(question)
    _check_expected(question, revision_id)
    if question.review_status != Question.ReviewStatus.REVIEWED or not question.current_revision_id:
        raise ValidationError("Review the current revision before publishing.")
    revision = question.current_revision
    revision.full_clean()
    if revision.published_at is None:
        revision.published_at = timezone.now()
        revision.save(_publishing=True, update_fields=["published_at"])
    question.published_revision = revision
    question.publication_status = Question.PublicationStatus.PUBLISHED
    question.save(_workflow=True)
    return question


def published_questions():
    """Safe reusable public queryset; never read current_revision for live content."""
    return Question.objects.filter(
        publication_status=Question.PublicationStatus.PUBLISHED,
        published_revision__published_at__isnull=False,
        published_revision__question_id=F("pk"),
    ).select_related("published_revision", "subject", "topic")


def get_published_revision(question):
    pk = question.pk if isinstance(question, Question) else question
    result = published_questions().filter(pk=pk).first()
    return result.published_revision if result else None
