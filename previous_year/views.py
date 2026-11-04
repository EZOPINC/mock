from django.db import transaction
from django.db.models import Case, Count, IntegerField, Prefetch, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_safe

from exams.models import Exam
from .models import PaperQuestion
from .services import published_papers
from .forms import PaperSelectionForm
from questions.models import QuestionTranslation


@require_safe
def index(request):
    exams = Exam.objects.filter(previous_year_papers__in=published_papers()).select_related("authority").annotate(
        paper_count=Count("previous_year_papers", distinct=True),
    ).order_by("authority__name", "name", "pk")
    return render(request, "previous_year/index.html", {"exams": exams})


def active_exam(authority_slug, exam_slug):
    return get_object_or_404(Exam.objects.select_related("authority"),
                             authority__slug=authority_slug, authority__is_active=True, slug=exam_slug, is_active=True)


@require_safe
def paper_list(request, authority_slug, exam_slug):
    exam = active_exam(authority_slug, exam_slug)
    groups = {}
    for paper in published_papers().filter(exam=exam):
        groups.setdefault(paper.year, []).append(paper)
    return render(request, "previous_year/paper_list.html", {"exam": exam,
        "year_groups": [{"year": year, "papers": papers} for year, papers in groups.items()]})


@require_safe
def paper_year(request, authority_slug, exam_slug, year):
    exam = active_exam(authority_slug, exam_slug)
    papers = published_papers().filter(exam=exam, year=year)
    count = papers.count()
    if not count:
        raise Http404
    form = PaperSelectionForm(request.GET if "paper" in request.GET else None, papers=papers)
    if form.is_bound:
        if form.is_valid():
            selected = form.cleaned_data["paper"]
        else:
            return render(request, "previous_year/paper_year.html", {"exam": exam, "year": year, "papers": papers, "paper_form": form}, status=400)
    elif count == 1:
        selected = papers.first()
    else:
        return render(request, "previous_year/paper_year.html", {"exam": exam, "year": year, "papers": papers, "paper_form": form})
    return redirect("previous_year:paper_detail", authority_slug=authority_slug, exam_slug=exam_slug, year=year, paper_id=selected.pk)


@require_safe
@transaction.atomic
def paper_detail(request, authority_slug, exam_slug, year, paper_id):
    exam = active_exam(authority_slug, exam_slug)
    # Keep unpublication/editing from changing rows during the public render.
    translations = QuestionTranslation.objects.annotate(_viewer_order=Case(
        When(language="en", then=Value(0)), When(language="bn", then=Value(1)), default=Value(2), output_field=IntegerField(),
    )).order_by("_viewer_order", "language", "pk")
    paper = get_object_or_404(published_papers().filter(exam=exam, year=year).select_for_update(of=("self",)).prefetch_related(
        Prefetch("paper_questions", queryset=PaperQuestion.objects.select_related(
            "question_revision").prefetch_related(Prefetch("question_revision__translations", queryset=translations))),
    ), pk=paper_id)
    siblings = published_papers().filter(exam=exam, year=year)
    selector = PaperSelectionForm(papers=siblings, initial={"paper": paper.pk}) if siblings.count() > 1 else None
    return render(request, "previous_year/paper_detail.html", {"paper": paper, "exam": exam, "paper_form": selector})
