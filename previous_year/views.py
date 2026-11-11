from django.db import transaction
from django.db.models import Case, Count, IntegerField, Prefetch, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_safe, require_POST
from django.views.decorators.cache import never_cache
from django.urls import reverse

from urllib.parse import urlencode

from exams.models import Exam
from .models import PaperQuestion
from .services import published_papers
from .forms import PaperSelectionForm
from questions.models import QuestionTranslation
from revision.services import attach_saved_state


@require_safe
def index(request):
    exams = Exam.objects.filter(previous_year_papers__in=published_papers()).select_related("authority").annotate(
        paper_count=Count("previous_year_papers", distinct=True),
    ).order_by("authority__name", "name", "pk")
    return render(request, "previous_year/index.html", {"exams": exams})


def active_exam(authority_slug, exam_slug):
    return get_object_or_404(Exam.objects.select_related("authority"),
                             authority__slug=authority_slug, authority__is_active=True, slug=exam_slug, is_active=True)


def stage_scope(request, papers):
    choices = list(papers.order_by("stage__display_order", "stage_id").values_list("stage_id", "stage__name").distinct())
    value = request.GET.get("stage")
    if value is not None:
        matching = [item for item in choices if str(item[0] or "none") == value]
        if not matching:
            raise Http404
        papers = papers.filter(stage_id=matching[0][0])
    elif len(choices) == 1:
        value = str(choices[0][0] or "none")
    return papers, choices, value


@require_safe
def paper_list(request, authority_slug, exam_slug):
    exam = active_exam(authority_slug, exam_slug)
    papers, stages, stage = stage_scope(request, published_papers().filter(exam=exam))
    groups = {}
    if stage is not None:
        for paper in papers:
            groups.setdefault(paper.year, []).append(paper)
    return render(request, "previous_year/paper_list.html", {"exam": exam,
        "stage_choices": stages if len(stages) > 1 else [], "selected_stage": stage,
        "stage_query": urlencode({"stage": stage}) if len(stages) > 1 and stage else "",
        "year_groups": [{"year": year, "papers": rows} for year, rows in groups.items()]})


def viewer_mode(request, default=None):
    mode = request.GET.get("mode", default)
    if mode is not None and mode not in {"direct", "practice"}:
        raise Http404
    return mode


@require_safe
def paper_year(request, authority_slug, exam_slug, year):
    exam = active_exam(authority_slug, exam_slug)
    mode = viewer_mode(request)
    papers, stages, stage = stage_scope(request, published_papers().filter(exam=exam, year=year))
    if not papers.exists():
        raise Http404
    sessions = list(papers.order_by("session").values_list("session", flat=True).distinct())
    session = request.GET.get("session")
    if session is not None:
        if session not in [item or "" for item in sessions]:
            raise Http404
        papers = papers.filter(session=session) if session else papers.filter(session__isnull=True)
    context = {"exam": exam, "year": year, "papers": papers, "selected_stage": stage, "selected_session": session, "viewer_mode": mode,
               "session_choices": [{"value": item or "", "label": item or "No session specified"} for item in sessions] if len(sessions) > 1 and session is None else []}
    form = PaperSelectionForm(request.GET if "paper" in request.GET else None, papers=papers)
    if form.is_bound:
        if form.is_valid():
            selected = form.cleaned_data["paper"]
        else:
            return render(request, "previous_year/paper_year.html", context | {"paper_form": form}, status=400)
    else:
        selected = papers.first() if papers.count() == 1 else None
    if mode is None:
        filters = {key: request.GET[key] for key in ("stage", "session", "paper") if key in request.GET}
        return render(request, "previous_year/modes.html", context | {
            "direct_query": urlencode(filters | {"mode": "direct"}),
            "practice_query": urlencode(filters | {"mode": "practice"}),
        })
    if selected is None:
        return render(request, "previous_year/paper_year.html", context | {"paper_form": form})
    return redirect(reverse("previous_year:paper_detail", args=[authority_slug, exam_slug, year, selected.pk]) + "?" + urlencode({"mode": mode}))


@never_cache
@require_safe
@transaction.atomic
def paper_detail(request, authority_slug, exam_slug, year, paper_id):
    context = paper_context(request, authority_slug, exam_slug, year, paper_id)
    return render(request, "previous_year/paper_detail.html", context)


def paper_context(request, authority_slug, exam_slug, year, paper_id):
    mode = viewer_mode(request, "direct")
    exam = active_exam(authority_slug, exam_slug)
    # Keep unpublication/editing from changing rows during the public render.
    translations = QuestionTranslation.objects.annotate(_viewer_order=Case(
        When(language="en", then=Value(0)), When(language="bn", then=Value(1)), default=Value(2), output_field=IntegerField(),
    )).order_by("_viewer_order", "language", "pk")
    paper = get_object_or_404(published_papers().filter(exam=exam, year=year).select_for_update(of=("self",)).prefetch_related(
        Prefetch("paper_questions", queryset=PaperQuestion.objects.select_related(
            "question_revision", "question__subject").prefetch_related(Prefetch("question_revision__translations", queryset=translations))),
    ), pk=paper_id)
    siblings = published_papers().filter(exam=exam, year=year)
    selector = PaperSelectionForm(papers=siblings, initial={"paper": paper.pk}) if siblings.count() > 1 else None
    counts = {}
    rows = list(paper.paper_questions.all())
    for row in rows:
        subject = row.question.subject
        counts.setdefault(subject.pk, {"id": subject.pk, "name": subject.name, "count": 0})["count"] += 1
    selected_subject = request.GET.get("subject", "")
    if selected_subject and selected_subject not in {str(pk) for pk in counts}:
        raise Http404
    viewer_rows = [row for row in rows if not selected_subject or str(row.question.subject_id) == selected_subject]
    for row in viewer_rows:
        row.bookmark_anchor = f"question-{row.pk}"
    attach_saved_state(request.user.pk if request.user.is_authenticated else None, viewer_rows)
    return {"paper": paper, "exam": exam, "paper_form": selector, "viewer_mode": mode,
        "question_count": len(rows), "subject_counts": sorted(counts.values(), key=lambda item: item["name"]),
        "selected_subject": selected_subject, "viewer_rows": viewer_rows, "answer_options": "ABCD"}


@never_cache
@require_POST
@transaction.atomic
def paper_answer(request, authority_slug, exam_slug, year, paper_id, row_id):
    if viewer_mode(request, "practice") != "practice":
        raise Http404
    context = paper_context(request, authority_slug, exam_slug, year, paper_id)
    context["viewer_mode"] = "practice"
    row = next((item for item in context["viewer_rows"] if item.pk == row_id), None)
    if row is None:
        raise Http404
    answer = request.POST.get("answer")
    valid_answer = answer in ("A", "B", "C", "D")
    status = 200 if valid_answer else 400
    if not valid_answer:
        row.practice_error = "Choose A, B, C or D."
    else:
        row.practice_answer = answer
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render(request, "previous_year/practice_question.html", context | {"row": row, "revision": row.question_revision}, status=status)
    return render(request, "previous_year/paper_detail.html", context, status=status)

