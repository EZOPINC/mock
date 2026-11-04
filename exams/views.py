from django.shortcuts import get_object_or_404, render
from django.db.models import Prefetch
from django.views.decorators.http import require_safe

from .models import Exam, ExamAuthority


@require_safe
def authorities(request):
    return render(request, "exams/authorities.html", {
        "authorities": ExamAuthority.objects.filter(is_active=True).prefetch_related(
            Prefetch("exams", queryset=Exam.objects.filter(is_active=True), to_attr="available_exams"),
        ),
    })


@require_safe
def exam_list(request, authority_slug):
    authority = get_object_or_404(ExamAuthority, slug=authority_slug, is_active=True)
    return render(request, "exams/exam_list.html", {
        "authority": authority,
        "exams": authority.exams.filter(is_active=True).prefetch_related("stages"),
    })


@require_safe
def exam_detail(request, authority_slug, exam_slug):
    exam = get_object_or_404(
        Exam.objects.select_related("authority"),
        authority__slug=authority_slug, authority__is_active=True,
        slug=exam_slug, is_active=True,
    )
    return render(request, "exams/exam_detail.html", {"exam": exam, "stages": exam.stages.all()})
