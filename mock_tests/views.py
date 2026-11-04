from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe
from questions.services import published_questions


@login_required
@require_safe
def preview(request, question_id=None):
    questions = published_questions().filter(exams__is_active=True, exams__authority__is_active=True).distinct()
    question = get_object_or_404(questions, pk=question_id) if question_id else None
    return render(request, "mock_tests/question_preview.html", {"question": question, "questions": questions.order_by("pk")[:20] if question is None else []})
