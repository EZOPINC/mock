from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe

from .models import ExamAuthority
from .selectors import active_authorities, active_exams


@require_safe
def authorities(request):
    return render(request, "exams/authorities.html", {
        "authorities": active_authorities(),
    })


@require_safe
def exam_list(request, authority_slug):
    authority = get_object_or_404(ExamAuthority, slug=authority_slug, is_active=True)
    return render(request, "exams/exam_list.html", {
        "authority": authority,
        "exams": active_exams().filter(authority=authority).prefetch_related("stages"),
    })


@require_safe
def exam_detail(request, authority_slug, exam_slug):
    exam = get_object_or_404(
        active_exams(), authority__slug=authority_slug, slug=exam_slug,
    )
    return render(request, "exams/exam_detail.html", {"exam": exam, "stages": exam.stages.all()})
