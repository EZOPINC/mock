from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Case, IntegerField, Prefetch, Value, When
import json
from math import ceil

from django.http import Http404, JsonResponse
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_safe

from exams.models import Exam, ExamAuthority
from questions.models import QuestionTranslation
from questions.services import published_questions
from .models import AttemptQuestion, ExamPattern, MockAttempt
from .services import available_patterns, start_attempt
from .execution import confirmation_counts, refresh_attempt, save_response, submit_attempt


@login_required
@require_safe
def preview(request, question_id=None):
    questions = published_questions().filter(exams__is_active=True, exams__authority__is_active=True).distinct()
    question = get_object_or_404(questions, pk=question_id) if question_id else None
    return render(request, "mock_tests/question_preview.html", {"question": question, "questions": questions.order_by("pk")[:20] if question is None else []})


@login_required
@require_safe
def index(request):
    for attempt in MockAttempt.objects.filter(user=request.user, status="in_progress", expires_at__lte=timezone.now()):
        refresh_attempt(request.user, attempt.pk)
    patterns = available_patterns()
    authority_ids = {pattern.exam.authority_id for pattern in patterns}
    return render(request, "mock_tests/index.html", {
        "authorities": ExamAuthority.objects.filter(pk__in=authority_ids),
        "attempts": MockAttempt.objects.filter(user=request.user, status__in=["created", "in_progress"]),
        "completed_attempts": MockAttempt.objects.filter(user=request.user, status__in=["submitted", "expired"])[:20],
    })


@login_required
@require_safe
def exam_list(request, authority_slug):
    authority = get_object_or_404(ExamAuthority, slug=authority_slug, is_active=True)
    ids = {pattern.exam_id for pattern in available_patterns(exam__authority=authority)}
    return render(request, "mock_tests/exams.html", {"authority": authority, "exams": authority.exams.filter(pk__in=ids)})


@login_required
@require_safe
def pattern_list(request, authority_slug, exam_slug):
    exam = get_object_or_404(Exam.objects.select_related("authority"), authority__slug=authority_slug,
        authority__is_active=True, slug=exam_slug, is_active=True)
    return render(request, "mock_tests/patterns.html", {"exam": exam, "patterns": available_patterns(exam=exam)})


@login_required
@require_http_methods(["GET", "HEAD", "POST"])
def test_start(request, pattern_id):
    pattern = get_object_or_404(ExamPattern.objects.select_related("exam__authority", "stage").prefetch_related("sections"), pk=pattern_id)
    existing = MockAttempt.objects.filter(user=request.user, pattern=pattern, status__in=["created", "in_progress"]).first()
    if existing:
        refresh_attempt(request.user, existing.pk)
        return redirect("mock_tests:attempt_detail", attempt_id=existing.pk)
    if not pattern.is_active or not pattern.exam.is_active or not pattern.exam.authority.is_active:
        raise Http404
    error = None
    if request.method == "POST":
        try:
            attempt = start_attempt(request.user, pattern)
        except ValidationError as exception:
            error = "; ".join(exception.messages)
        else:
            return redirect("mock_tests:attempt_detail", attempt_id=attempt.pk)
    elif not any(item.pk == pattern.pk for item in available_patterns(pk=pattern.pk)):
        raise Http404
    return render(request, "mock_tests/start.html", {"pattern": pattern, "error": error}, status=400 if error else 200)


@login_required
@never_cache
@require_safe
def attempt_detail(request, attempt_id):
    state = refresh_attempt(request.user, attempt_id)
    if state.is_finalized:
        return redirect("mock_tests:results", attempt_id=attempt_id)
    return render(request, "mock_tests/attempt.html", attempt_context(request, attempt_id))


def attempt_context(request, attempt_id):
    translations = QuestionTranslation.objects.annotate(_language_order=Case(
        When(language="en", then=Value(0)), When(language="bn", then=Value(1)), default=Value(2), output_field=IntegerField(),
    )).order_by("_language_order", "language", "pk")
    attempt = get_object_or_404(MockAttempt.objects.prefetch_related(Prefetch("questions",
        queryset=AttemptQuestion.objects.select_related("question_revision", "question__subject").prefetch_related(
            Prefetch("question_revision__translations", queryset=translations)))), pk=attempt_id, user=request.user)
    sections = {item["id"]: item for item in attempt.configuration["sections"]}
    rows = list(attempt.questions.all())
    for row in rows:
        row.section_snapshot = sections[row.section_id]
    return {"attempt": attempt, "rows": rows, "options": "ABCD", "clock": {
        "server_now": timezone.now().isoformat(), "deadline": attempt.expires_at.isoformat() if attempt.expires_at else None,
        "version": attempt.save_version, "position": attempt.last_position,
    }}


@login_required
@never_cache
@require_http_methods(["POST"])
def save_answer(request, attempt_id):
    try:
        if len(request.body) > 4096:
            raise ValidationError("Save request is too large.")
        payload = json.loads(request.body)
        result = save_response(request.user, attempt_id, payload)
    except (ValueError, UnicodeDecodeError, RecursionError, ValidationError) as error:
        return JsonResponse({"ok": False, "error": "; ".join(error.messages) if isinstance(error, ValidationError) else "Invalid save request."}, status=400)
    return JsonResponse(result, status=result["status"])


@login_required
@never_cache
@require_safe
def attempt_status(request, attempt_id):
    attempt = refresh_attempt(request.user, attempt_id)
    return JsonResponse({"finalized": attempt.is_finalized, "server_now": timezone.now().isoformat(),
        "deadline": attempt.expires_at.isoformat() if attempt.expires_at else None,
        "result_url": reverse("mock_tests:results", args=[attempt.pk])})


@login_required
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def confirm_submit(request, attempt_id):
    attempt = refresh_attempt(request.user, attempt_id)
    if attempt.is_finalized:
        return redirect("mock_tests:results", attempt_id=attempt.pk)
    error = None
    if request.method == "POST":
        try:
            version = int(request.POST.get("version", ""))
            if version < 0:
                raise ValueError
            submit_attempt(request.user, attempt.pk, expected_version=version)
        except (ValueError, ValidationError) as exception:
            error = "; ".join(exception.messages) if isinstance(exception, ValidationError) else "A valid confirmation version is required."
            attempt = refresh_attempt(request.user, attempt_id)
        else:
            return redirect("mock_tests:results", attempt_id=attempt.pk)
    return render(request, "mock_tests/confirm.html", {"attempt": attempt, "counts": confirmation_counts(attempt), "error": error,
        "deadline_seconds": max(1, ceil((attempt.expires_at - timezone.now()).total_seconds()))}, status=409 if error else 200)


@login_required
@never_cache
@require_safe
def results(request, attempt_id):
    attempt = refresh_attempt(request.user, attempt_id)
    if not attempt.is_finalized:
        return redirect("mock_tests:attempt_detail", attempt_id=attempt.pk)
    context = attempt_context(request, attempt_id)
    context["attempted_count"] = attempt.correct_count + attempt.incorrect_count
    return render(request, "mock_tests/results.html", context)
