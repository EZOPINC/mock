"""Revision selection and progress; Practice owns snapshots, answers and completion."""
from secrets import SystemRandom
from uuid import UUID
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from practice.models import PracticeSession
from practice.services import assemble_session
from questions.models import Question
from .forms import RevisionStartForm
from .models import RevisionSession, SavedQuestion
from .selectors import bank_rows, filter_bank, visible_questions

FILTER_FIELDS = ("exam", "subject", "part", "module", "chapter", "topic", "mastery")


def request_spec(parameters):
    spec = {}
    for field in FILTER_FIELDS:
        value = parameters.get(field, "") or ""
        if field != "mastery" and value:
            try:
                value = str(int(value))
            except (TypeError, ValueError):
                raise ValidationError("Choose a valid revision filter.")
            if int(value) <= 0:
                raise ValidationError("Choose a valid revision filter.")
        spec[field] = value
    if spec["mastery"] not in {"", "mastered", "needs_revision"}:
        raise ValidationError("Choose a valid mastery status.")
    limit = parameters.get("question_limit", "") or ""
    if limit:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ValidationError("Choose a valid question limit.")
        if not 1 <= limit <= 10000:
            raise ValidationError("Choose a limit between 1 and 10,000, or leave it blank for all questions.")
    spec["question_limit"] = limit
    return spec


@transaction.atomic
def start_revision(user, parameters):
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied
    try:
        token = UUID(str(parameters.get("token", "")))
    except (TypeError, ValueError, AttributeError):
        raise ValidationError("Reload the revision setup page before starting.")
    spec = request_spec(parameters)
    get_user_model().objects.select_for_update().get(pk=user.pk)
    existing = PracticeSession.objects.filter(user=user, start_token=token).first()
    if existing:
        if existing.kind != "revision" or existing.configuration.get("revision_request") != spec:
            raise ValidationError("This start token belongs to another session setup. Reload before starting.")
        return RevisionSession.objects.get(pk=existing.pk)
    form = RevisionStartForm(parameters, user=user)
    if not form.is_valid():
        raise ValidationError([message for errors in form.errors.values() for message in errors])
    values = form.cleaned_data

    def selected_ids():
        return set(filter_bank(bank_rows(user), values).filter(content_available=True)
                   .order_by().values_list("question_id", flat=True).distinct())

    ids = selected_ids()
    # The Question lock also serializes publication and retagging workflows.
    list(Question.objects.select_for_update().filter(pk__in=ids).order_by("pk").values_list("pk", flat=True))
    ids &= selected_ids()
    if not ids:
        raise ValidationError("No eligible saved questions match this selection. Change your filters or save more questions.")
    selected = SystemRandom().sample(sorted(ids), min(spec["question_limit"] or len(ids), len(ids)))
    questions = {q.pk: q for q in visible_questions(user).filter(pk__in=selected).select_related("published_revision", "subject", "topic")}
    if len(questions) != len(selected):
        raise ValidationError("Question availability changed. Review your selection and try again.")
    configuration = {"exam_name": "My Revision Bank", "authority_name": "Personal revision",
        "subject_name": values["subject"].name if values.get("subject") else "Saved questions",
        "topic_name": values["topic"].name if values.get("topic") else "Saved topics",
        "requested_count": str(spec["question_limit"] or "available"), "total_questions": len(selected),
        "revision_request": spec,
        "filter_labels": {field: str(values[field].name if hasattr(values[field], "name") else values[field])
                          for field in FILTER_FIELDS if values.get(field)}}
    session = assemble_session(user, questions=[questions[pk] for pk in selected], configuration=configuration,
                               token=token, kind="revision")
    return RevisionSession.objects.get(pk=session.pk)


def record_review(session, row):
    """Called once after the Practice engine first locks an answer, in its transaction."""
    SavedQuestion.objects.filter(user_id=session.user_id, question_id=row.question_id).update(
        reviewed_at=timezone.now(), review_count=F("review_count") + 1)
