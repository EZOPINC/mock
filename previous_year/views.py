from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe

from exams.models import Exam
from .models import PaperQuestion
from .services import published_papers


@require_safe
def index(request):
    return render(request, "previous_year/index.html", {"papers": published_papers()})


def active_exam(authority_slug, exam_slug):
    return get_object_or_404(Exam.objects.select_related("authority"),
                             authority__slug=authority_slug, authority__is_active=True, slug=exam_slug, is_active=True)


@require_safe
def paper_list(request, authority_slug, exam_slug):
    exam = active_exam(authority_slug, exam_slug)
    return render(request, "previous_year/paper_list.html", {"exam": exam, "papers": published_papers().filter(exam=exam)})


@require_safe
@transaction.atomic
def paper_detail(request, authority_slug, exam_slug, year, paper_id):
    exam = active_exam(authority_slug, exam_slug)
    # Keep unpublication/editing from changing rows during the public render.
    paper = get_object_or_404(published_papers().filter(exam=exam, year=year).select_for_update(of=("self",)).prefetch_related(
        Prefetch("paper_questions", queryset=PaperQuestion.objects.select_related(
            "question_revision")),
    ), pk=paper_id)
    return render(request, "previous_year/paper_detail.html", {"paper": paper, "exam": exam})
