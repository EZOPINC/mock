"""Explicit whole-General-batch review/publication; no import auto-publication."""
import hashlib
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from questions.models import Question
from questions.services import mark_reviewed, publish_question
from .models import GeneralQuestionBatch


def require_batch_permission(user):
    if not user.is_active or not user.is_staff or not user.has_perms(("imports.view_importbatch", "questions.change_question")):
        raise PermissionDenied("Viewing import batches and changing questions are required.")


def general_batches():
    return GeneralQuestionBatch.objects.all()


def batch_questions(batch):
    return Question.objects.filter(pk__in=batch.imported_questions.values("question_id")).order_by("pk")


def fingerprint(questions):
    state = [(question.pk, question.current_revision_id, question.review_status, question.published_revision_id) for question in questions]
    return hashlib.sha256(json.dumps(state).encode()).hexdigest()


@transaction.atomic
def transition_batch(batch_id, user, action, expected):
    user = get_user_model().objects.get(pk=user.pk)
    require_batch_permission(user)
    if action not in {"review", "publish"}:
        raise ValidationError("Choose review or publish.")
    batch = general_batches().select_for_update().get(pk=batch_id)
    questions = list(batch_questions(batch).select_for_update())
    if not questions:
        raise ValidationError("This collection has no questions.")
    if fingerprint(questions) != expected:
        raise ValidationError("This batch changed. Reload and inspect its working revisions before continuing.")
    operation = mark_reviewed if action == "review" else publish_question
    for question in questions:
        operation(question, revision_id=question.current_revision_id)
    return len(questions)
