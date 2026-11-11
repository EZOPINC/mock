from decimal import Decimal
from secrets import SystemRandom
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from questions.models import Question
from .models import PracticeQuestion, PracticeSession
from .discovery import PracticeTaxonomy, configuration_matches, difficulty_pools


COUNTS = ("10", "20", "30", "50", "available")


@transaction.atomic
def start_session(user, *, exam, subject, topic=None, part=None, module=None, chapter=None, count="available", token, difficulty=None):
    if not user.is_authenticated or not user.is_active:
        raise ValidationError("An active authenticated account is required.")
    difficulty = difficulty.strip().casefold() if difficulty is not None else None
    count = str(count)
    if count not in COUNTS:
        raise ValidationError("Choose 10, 20, 30, 50 or the available count.")
    try:
        token = UUID(str(token))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("A valid start token is required.")
    get_user_model().objects.select_for_update().get(pk=user.pk)
    filters = {"part": part, "module": module, "chapter": chapter, "topic": topic}
    existing = PracticeSession.objects.filter(user=user, start_token=token).first()
    if existing:
        if not configuration_matches(existing, exam_id=exam.pk, subject_id=subject.pk, count=count, filters=filters, difficulty=difficulty):
            raise ValidationError("This start token belongs to another configuration. Reload the start page.")
        return existing
    scope = PracticeTaxonomy(exam, subject)
    ids = scope.selected_ids(filters)
    list(Question.objects.select_for_update().filter(pk__in=ids).order_by("pk").values_list("pk", flat=True))
    # Retagging locks Question in D3; re-read tags and eligibility after acquiring masters.
    scope = PracticeTaxonomy(exam, subject)
    ids &= scope.selected_ids(filters)
    if difficulty is not None:
        ids &= difficulty_pools(ids).get(difficulty, set())
    required = len(ids) if count == "available" else int(count)
    if not required or required > len(ids):
        raise ValidationError("Insufficient eligible questions. Change the count or topic and try again; no session was created.")
    selected = SystemRandom().sample(sorted(ids), required)
    questions = {item.pk: item for item in Question.objects.filter(pk__in=selected).select_related("published_revision", "subject", "topic")}
    configuration = {"exam_name": exam.name, "authority_name": exam.authority.name,
            "subject_name": subject.name, "topic_name": topic.name if topic else "All topics",
            "difficulty": difficulty, "module_name": module.name if module else "Whole subject",
            "difficulty_label": (difficulty.title() if difficulty else "Unspecified difficulty") if difficulty is not None else "All difficulties",
            "requested_count": count, "total_questions": required, "taxonomy_filters": scope.snapshot(filters)}
    return assemble_session(user, questions=[questions[pk] for pk in selected], configuration=configuration,
        token=token, exam=exam, subject=subject, topic=topic)


@transaction.atomic
def assemble_session(user, *, questions, configuration, token, exam=None, subject=None, topic=None, kind="practice"):
    """Shared assembly of immutable question/revision/order snapshots."""
    session = PracticeSession(user=user, exam=exam, subject=subject, topic=topic, start_token=token,
                              configuration=configuration, kind=kind)
    session.save(_assembly=True)
    for order, question in enumerate(questions, 1):
        PracticeQuestion(session=session, question=question, question_revision=question.published_revision,
            display_order=order, classification={"subject_id": question.subject_id, "subject_name": question.subject.name,
                "topic_id": question.topic_id, "topic_name": question.topic.name if question.topic else "No topic"}).save(_assembly=True)
    return session


@transaction.atomic
def submit_answer(user, session_id, question_id, answer):
    session = get_object_or_404(PracticeSession.objects.select_for_update(), pk=session_id, user=user)
    row = get_object_or_404(PracticeQuestion.objects.select_related("question_revision"), pk=question_id, session=session)
    if answer not in ("A", "B", "C", "D"):
        raise ValidationError("Select A, B, C or D before submitting.")
    if row.selected_answer:
        if row.selected_answer == answer:
            return row
        raise ValidationError("This answer is locked because feedback has already been revealed.")
    if session.status != PracticeSession.Status.IN_PROGRESS:
        raise ValidationError("This practice session is closed.")
    row.selected_answer = answer
    row.is_correct = answer == row.question_revision.correct_answer
    row.answered_at = timezone.now()
    row.save(_feedback=True)
    if session.kind == PracticeSession.Kind.REVISION:
        from revision.sessions import record_review
        record_review(session, row)
    if not session.questions.filter(selected_answer="").exists():
        session.status = PracticeSession.Status.COMPLETED
        session.completed_at = timezone.now()
        session.save(_transition=True)
    return row


@transaction.atomic
def abandon_session(user, session_id):
    session = get_object_or_404(PracticeSession.objects.select_for_update(), pk=session_id, user=user)
    if session.status == PracticeSession.Status.IN_PROGRESS:
        session.status = PracticeSession.Status.ABANDONED
        session.completed_at = timezone.now()
        session.save(_transition=True)
    return session


def progress(rows):
    rows = list(rows)
    answered = sum(bool(row.selected_answer) for row in rows)
    correct = sum(row.is_correct is True for row in rows)
    return {"total": len(rows), "answered": answered, "correct": correct,
        "incorrect": answered - correct, "remaining": len(rows) - answered,
        "accuracy": (Decimal(correct) * 100 / answered).quantize(Decimal("0.01")) if answered else Decimal(0),
        "percent": (Decimal(answered) * 100 / len(rows)).quantize(Decimal("0.01")) if rows else Decimal(0)}


def performance(rows, kind):
    groups = {}
    for row in rows:
        key = row.classification[f"{kind}_id"]
        groups.setdefault(key, {"name": row.classification[f"{kind}_name"], "rows": []})["rows"].append(row)
    return [dict(name=item["name"], **progress(item["rows"])) for item in groups.values()]


@transaction.atomic
def complete_session(user, session_id):
    """Finish a revision early, retaining unanswered rows and immutable history."""
    session = get_object_or_404(PracticeSession.objects.select_for_update(), pk=session_id, user=user, kind="revision")
    if session.status == PracticeSession.Status.IN_PROGRESS:
        session.status = PracticeSession.Status.COMPLETED
        session.completed_at = timezone.now()
        session.save(_transition=True)
    return session
