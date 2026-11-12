from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Case, IntegerField, Prefetch, Value, When
from uuid import UUID

from django.http import Http404
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from exams.models import Exam, ExamAuthority, Subject
from questions.eligibility import eligible_question_ids
from questions.models import Question, QuestionTranslation
from .forms import PracticeDifficultyForm
from .discovery import LEVELS, PracticeTaxonomy, configuration_matches, difficulty_pools
from .models import PracticeQuestion, PracticeSession
from revision.services import attach_saved_state
from .services import abandon_session, performance, progress, start_session, submit_answer


def exam_from_slugs(authority_slug, exam_slug):
    return get_object_or_404(Exam.objects.select_related("authority"), authority__slug=authority_slug,
        authority__is_active=True, slug=exam_slug, is_active=True)


def session_for(user, session_id):
    return get_object_or_404(PracticeSession, pk=session_id, user=user, kind="practice")


@login_required
@never_cache
@require_safe
def index(request):
    ids = [exam.pk for exam in Exam.objects.filter(is_active=True, authority__is_active=True) if eligible_question_ids(exam.pk)]
    return render(request, "practice/index.html", {
        "authorities": ExamAuthority.objects.filter(exams__pk__in=ids).distinct(),
        "open_sessions": PracticeSession.objects.filter(user=request.user, kind="practice", status="in_progress"),
        "closed_sessions": PracticeSession.objects.filter(user=request.user, kind="practice").exclude(status="in_progress")[:20],
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
        if existing and configuration_matches(existing, exam_id=exam.pk, subject_id=subject.pk, count=request.POST.get("count"), filters={kind: request.POST.get(kind) for kind in LEVELS}):
            return redirect("practice:session", session_id=existing.pk)
    scope = PracticeTaxonomy(exam, subject)
    modules = [{"module": scope.nodes["module"][pk], "count": len(ids)}
               for pk, ids in scope.pools["module"].items()]
    modules.sort(key=lambda item: (item["module"].name.casefold(), item["module"].pk))
    return render(request, "practice/configure.html", {"exam": exam, "subject": subject,
        "modules": modules, "available_count": len(scope.question_ids),
        "setup_error": "Choose a module and difficulty to start a new session." if request.method == "POST" else ""},
        status=400 if request.method == "POST" else 200)


@login_required
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def difficulty(request, authority_slug, exam_slug, subject_slug, module_id=None):
    exam = exam_from_slugs(authority_slug, exam_slug)
    subject = get_object_or_404(Subject, slug=subject_slug)
    scope = PracticeTaxonomy(exam, subject)
    module = scope.nodes["module"].get(module_id) if module_id is not None else None
    if module_id is not None and module is None:
        raise Http404
    filters = {"module": module}
    if request.method == "POST":
        try:
            token = UUID(request.POST.get("token", ""))
        except (ValueError, TypeError, AttributeError):
            token = None
        existing = PracticeSession.objects.filter(user=request.user, start_token=token).first() if token else None
        value = request.POST.get("difficulty", "")
        if existing and value.startswith("level:") and configuration_matches(existing,
                exam_id=exam.pk, subject_id=subject.pk, count="available", filters=filters, difficulty=value[6:]):
            return redirect("practice:session", session_id=existing.pk)
    pools = difficulty_pools(scope.selected_ids(filters))
    form = PracticeDifficultyForm(request.POST if request.method == "POST" else None, pools=pools)
    if request.method == "POST" and form.is_valid():
        try:
            session = start_session(request.user, exam=exam, subject=subject, module=module,
                difficulty=form.cleaned_data["difficulty"], token=form.cleaned_data["token"])
        except ValidationError as error:
            form.add_error(None, error)
        else:
            request.session[f"practice_language_{session.pk}"] = form.cleaned_data["language"] or "both"
            return redirect("practice:session", session_id=session.pk)
    return render(request, "practice/difficulty.html", {"exam": exam, "subject": subject,
        "module": module, "form": form, "available_count": sum(map(len, pools.values()))},
        status=400 if request.method == "POST" and form.errors else 200)


def question_context(session, row, *, translations=None, language="both"):
    translations = translations if translations is not None else QuestionTranslation.objects.annotate(_order=Case(When(language="en", then=Value(0)),
        When(language="bn", then=Value(1)), default=Value(2), output_field=IntegerField())).order_by("_order", "language", "pk")
    if language in {"en", "bn"} and translations.filter(revision_id=row.question_revision_id, language=language).exists():
        translations = translations.filter(language=language)
    row = PracticeQuestion.objects.select_related("question_revision").prefetch_related(
        Prefetch("question_revision__translations", queryset=translations)).get(pk=row.pk, session=session)
    rows = list(session.questions.all())
    attach_saved_state(session.user_id, [row])
    return {"session": session, "row": row, "rows": rows, "progress": progress(rows), "options": "ABCD",
            "answer_url": reverse("practice:answer", args=[session.pk, row.pk])}


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
    return render(request, "practice/session.html", question_context(session, row,
        language=request.session.get(f"practice_language_{session.pk}", "both")))


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
        return render(request, "practice/session.html", question_context(session, row,
            language=request.session.get(f"practice_language_{session.pk}", "both")) | {"error": "; ".join(error.messages)}, status=400)
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
