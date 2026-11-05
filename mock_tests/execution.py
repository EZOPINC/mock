"""Server-authoritative attempt execution. Every mutation locks the parent first."""
from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import AttemptQuestion, MockAttempt


def _locked(user, attempt_id):
    return get_object_or_404(MockAttempt.objects.select_for_update(), pk=attempt_id, user=user)


def _finalize(attempt, *, expired=False):
    if attempt.is_finalized:
        return attempt
    if attempt.status != MockAttempt.Status.IN_PROGRESS:
        raise ValidationError("This attempt has not started.")
    rows = list(attempt.questions.select_for_update(of=("self",)).select_related("question_revision"))
    if len(rows) != attempt.configuration["total_questions"]:
        raise ValidationError("Attempt question count is inconsistent; contact an administrator.")
    sections = {str(item["id"]): {"name": item["name"], "correct": 0, "incorrect": 0,
        "unanswered": 0, "score": Decimal(0), "maximum": Decimal(0)} for item in attempt.configuration["sections"]}
    score, maximum, correct, incorrect, unanswered = Decimal(0), Decimal(0), 0, 0, 0
    for row in rows:
        section = sections[str(row.section_id)]
        if not row.selected_answer:
            row.awarded_marks = Decimal(0)
            unanswered += 1
            section["unanswered"] += 1
        elif row.selected_answer == row.question_revision.correct_answer:
            row.awarded_marks = row.positive_marks
            correct += 1
            section["correct"] += 1
        else:
            row.awarded_marks = -row.negative_marks
            incorrect += 1
            section["incorrect"] += 1
        row.save(_execution=True, update_fields=["awarded_marks"])
        score += row.awarded_marks
        maximum += row.positive_marks
        section["score"] += row.awarded_marks
        section["maximum"] += row.positive_marks
    for section in sections.values():
        section["score"] = str(section["score"])
        section["maximum"] = str(section["maximum"])
    attempt.status = MockAttempt.Status.EXPIRED if expired else MockAttempt.Status.SUBMITTED
    attempt.finalized_at = attempt.expires_at if expired else timezone.now()
    attempt.total_score, attempt.maximum_score = score, maximum
    attempt.correct_count, attempt.incorrect_count, attempt.unanswered_count = correct, incorrect, unanswered
    attempt.section_results = sections
    attempt.save(_execution=True)
    return attempt


def _expire(attempt):
    if attempt.status == MockAttempt.Status.IN_PROGRESS and attempt.expires_at <= timezone.now():
        return _finalize(attempt, expired=True)
    return attempt


@transaction.atomic
def refresh_attempt(user, attempt_id):
    return _expire(_locked(user, attempt_id))


@transaction.atomic
def submit_attempt(user, attempt_id, *, expected_version=None):
    attempt = _expire(_locked(user, attempt_id))
    if attempt.is_finalized:
        return attempt
    if expected_version is not None and expected_version != attempt.save_version:
        raise ValidationError("Answers changed after confirmation. Review the updated counts and confirm again.")
    return _finalize(attempt)


@transaction.atomic
def save_response(user, attempt_id, payload):
    attempt = _expire(_locked(user, attempt_id))
    base = {"version": attempt.save_version, "finalized": attempt.is_finalized}
    if attempt.is_finalized:
        return base | {"ok": False, "status": 410, "error": "This attempt is finalized. Answers cannot change."}
    if not isinstance(payload, dict):
        raise ValidationError("Expected an answer object.")
    version = payload.get("version")
    try:
        token = UUID(str(payload.get("token", "")))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("A valid save token is required.")
    if type(version) is not int or version < 0:
        raise ValidationError("A nonnegative save version is required.")
    if token == attempt.last_save_token and version == attempt.save_version - 1:
        return base | {"ok": True, "status": 200}
    if version != attempt.save_version:
        return base | {"ok": False, "status": 409, "error": "This attempt changed in another request. Reload before editing."}
    action = payload.get("action")
    position = payload.get("position")
    if type(position) is not int or not attempt.questions.filter(display_order=position).exists():
        raise ValidationError("Choose a question position belonging to this attempt.")
    if action == "answer":
        question_id = payload.get("question_id")
        if type(question_id) is not int:
            raise ValidationError("A valid attempt question ID is required.")
        row = get_object_or_404(AttemptQuestion, pk=question_id, attempt=attempt)
        answer, review = payload.get("answer"), payload.get("review")
        if answer not in ("", "A", "B", "C", "D") or type(review) is not bool:
            raise ValidationError("Answer must be A/B/C/D or blank, with a boolean review flag.")
        row.selected_answer, row.marked_for_review = answer, review
        row.answered_at = timezone.now() if answer else None
        row.save(_execution=True, update_fields=["selected_answer", "marked_for_review", "answered_at"])
    elif action != "position":
        raise ValidationError("Unknown save action.")
    attempt.last_position = position
    attempt.save_version += 1
    attempt.last_save_token = token
    attempt.save(_execution=True, update_fields=["last_position", "save_version", "last_save_token"])
    return {"ok": True, "status": 200, "version": attempt.save_version, "finalized": False}


def confirmation_counts(attempt):
    rows = list(attempt.questions.all())
    answered = sum(bool(row.selected_answer) for row in rows)
    return {"answered": answered, "unanswered": len(rows) - answered,
        "review": sum(row.marked_for_review for row in rows)}
