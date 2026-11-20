from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from previous_year.models import QuestionAppearance
from .appearance_forms import AppearanceForm
from .review_services import imported_questions
from .review_views import queue_url
from .services import require_batch_permission


@staff_member_required
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def edit_appearance(request, question_id, appearance_id=None):
    require_batch_permission(request.user)
    saving = request.method == "POST"
    back = queue_url("review_question", request.GET.urlencode(), question_id)
    with transaction.atomic():
        questions = imported_questions()
        if saving:
            questions = questions.select_for_update()
        question = get_object_or_404(questions, pk=question_id)
        appearances = question.exam_appearances
        if saving:
            appearances = appearances.select_for_update()
        appearance = get_object_or_404(appearances, pk=appearance_id) if appearance_id else QuestionAppearance(question=question)
        form = AppearanceForm(request.POST if saving else None, instance=appearance)
        if saving and form.is_valid():
            try:
                form.save_for_reviewer(request.user)
            except ValidationError as error:
                form.add_error(None, "; ".join(error.messages))
            else:
                messages.success(request, "Exam appearance saved.")
                return redirect(back)
    return render(request, "general_question/appearance_form.html", {
        "question": question, "form": form, "back": back, "appearance": appearance,
    }, status=400 if saving else 200)
