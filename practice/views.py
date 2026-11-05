from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Case, IntegerField, Prefetch, Value, When
from collections import Counter
from uuid import UUID

from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from exams.models import Exam, ExamAuthority, Subject
from questions.eligibility import eligible_question_ids
from questions.models import Question, QuestionTranslation
from .forms import PracticeStartForm
from .models import PracticeQuestion, PracticeSession
from .services import abandon_session, performance, progress, start_session, submit_answer


def exam_from_slugs(authority_slug, exam_slug):
    return get_object_or_404(Exam.objects.select_related("authority"), authority__slug=authority_slug,
        authority__is_active=True, slug=exam_slug, is_active=True)


def session_for(user, session_id):
    return get_object_or_404(PracticeSession, pk=session_id, user=user)


@login_required
@never_cache
@require_safe
def index(request):
    ids = [exam.pk for exam in Exam.objects.filter(is_active=True, authority__is_active=True) if eligible_question_ids(exam.pk)]
    return render(request, "practice/index.html", {
        "authorities": ExamAuthority.objects.filter(exams__pk__in=ids).distinct(),
        "open_sessions": PracticeSession.objects.filter(user=request.user, status="in_progress"),
        "closed_sessions": PracticeSession.objects.filter(user=request.user).exclude(status="in_progress")[:20],
    })


@login_required
@require_safe
def exams(request, authority_slug):
    authority = get_object_or_404(ExamAuthority, slug=authority_slug, is_active=True)
    available = [exam for exam in authority.exams.filter(is_active=True) if eligible_question_ids(exam.pk)]
    return render(request, "practice/exams.html", {"authority": authority, "exams": available})


@login_required
@require_safe
def subjects(request, authority_slug, exam_slug):
    exam = exam_from_slugs(authority_slug, exam_slug)
    ids = eligible_question_ids(exam.pk)
    available = Subject.objects.filter(questions__pk__in=ids).distinct()
    return render(request, "practice/subjects.html", {"exam": exam, "subjects": available})


@login_required
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def configure(request, authority_slug, exam_slug, subject_slug):
    exam = exam_from_slugs(authority_slug, exam_slug)
    subject = get_object_or_404(Subject, slug=subject_slug)
    if request.method == "POST":
        try:
            token = UUID(request.POST.get("token", ""))
        except (ValueError, TypeError, AttributeError):
            token = None
        existing = PracticeSession.objects.filter(user=request.user, start_token=token).first() if token else None
        if existing and existing.exam_id == exam.pk and existing.subject_id == subject.pk and str(existing.topic_id or "") == request.POST.get("topic", "") and existing.configuration["requested_count"] == request.POST.get("count"):
            return redirect("practice:session", session_id=existing.pk)
    ids = eligible_question_ids(exam.pk, subject_id=subject.pk)
    if not ids:
        raise Http404
    topic_counts = Counter(Question.objects.filter(pk__in=ids).values_list("topic_id", flat=True))
    topic_ids = set(topic_counts) - {None}
    form = PracticeStartForm(request.POST if request.method == "POST" else None,
        topic_ids=topic_ids, available_count=len(ids))
    if request.method == "POST" and form.is_valid():
        try:
            session = start_session(request.user, exam=exam, subject=subject, topic=form.cleaned_data["topic"],
                count=form.cleaned_data["count"], token=form.cleaned_data["token"])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            return redirect("practice:session", session_id=session.pk)
    topics = [{"topic": topic, "count": topic_counts[topic.pk]} for topic in form.fields["topic"].queryset]
    return render(request, "practice/configure.html", {"exam": exam, "subject": subject, "form": form,
        "available_count": len(ids), "topics": topics}, status=400 if request.method == "POST" and form.errors else 200)


def question_context(session, row):
    translations = QuestionTranslation.objects.annotate(_order=Case(When(language="en", then=Value(0)),
        When(language="bn", then=Value(1)), default=Value(2), output_field=IntegerField())).order_by("_order", "language", "pk")
    row = PracticeQuestion.objects.select_related("question_revision").prefetch_related(
        Prefetch("question_revision__translations", queryset=translations)).get(pk=row.pk, session=session)
    rows = list(session.questions.all())
    return {"session": session, "row": row, "rows": rows, "progress": progress(rows), "options": "ABCD"}


@login_required
@never_cache
@require_safe
def session_view(request, session_id):
    session = session_for(request.user, session_id)
    rows = list(session.questions.all())
    if not rows:
        raise Http404
    value = request.GET.get("question")
    if value is None:
        row = next((item for item in rows if not item.selected_answer), rows[0])
    else:
        try:
            order = int(value)
        except (TypeError, ValueError):
            raise Http404
        row = next((item for item in rows if item.display_order == order), None)
        if row is None:
            raise Http404
    return render(request, "practice/session.html", question_context(session, row))


@login_required
@never_cache
@require_http_methods(["POST"])
def answer(request, session_id, question_id):
    session = session_for(request.user, session_id)
    row = get_object_or_404(PracticeQuestion, pk=question_id, session=session)
    try:
        row = submit_answer(request.user, session_id, question_id, request.POST.get("answer"))
    except ValidationError as error:
        session.refresh_from_db()
        return render(request, "practice/session.html", question_context(session, row) | {"error": "; ".join(error.messages)}, status=400)
    from django.urls import reverse
    return redirect(reverse("practice:session", args=[session.pk]) + f"?question={row.display_order}")


@login_required
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def abandon(request, session_id):
    session = session_for(request.user, session_id)
    if request.method == "POST":
        abandon_session(request.user, session_id)
        return redirect("practice:summary", session_id=session_id)
    return render(request, "practice/abandon.html", {"session": session, "progress": progress(session.questions.all())})


@login_required
@never_cache
@require_safe
def summary(request, session_id):
    session = session_for(request.user, session_id)
    rows = list(session.questions.all())
    return render(request, "practice/summary.html", {"session": session, "rows": rows,
        "progress": progress(rows), "subject_performance": performance(rows, "subject"), "topic_performance": performance(rows, "topic")})
