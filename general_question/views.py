from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from general_question.services import batch_questions, fingerprint, general_batches, require_batch_permission, transition_batch
from .forms import GeneralQuestionFilters
from questions.services import published_questions

SALT = "general-question-batch-publication"


def public_questions():
    return published_questions().filter(
        import_records__batch__in=general_batches(),
        exams__is_active=True, exams__authority__is_active=True,
    ).distinct()


def filtered(request):
    form = GeneralQuestionFilters(request.GET)
    questions = public_questions()
    if form.is_valid():
        for field in ("exam", "subject", "topic"):
            if form.cleaned_data[field]:
                questions = questions.filter(**{"exams" if field == "exam" else field: form.cleaned_data[field]})
        if form.cleaned_data["language"]:
            questions = questions.filter(published_revision__language=form.cleaned_data["language"])
    else:
        questions = questions.none()
    parameters = request.GET.copy()
    parameters.pop("page", None)
    return form, questions, parameters.urlencode()


@require_safe
def index(request):
    form, questions, query = filtered(request)
    batches = general_batches().annotate(public_count=Count(
        "imported_questions__question", filter=Q(imported_questions__question__in=questions), distinct=True,
    )).filter(public_count__gt=0).order_by("-created_at", "-pk")
    return render(request, "general_question/index.html", {"form": form, "page": Paginator(batches, 20).get_page(request.GET.get("page")), "query": query})


@require_safe
def collection(request, batch_id):
    # Draft-only collections return 404, even if the ID is guessed.
    batch = get_object_or_404(general_batches().filter(imported_questions__question__in=public_questions()).distinct(), pk=batch_id)
    form, questions, query = filtered(request)
    questions = questions.filter(import_records__batch=batch).order_by("pk").distinct()
    return render(request, "general_question/collection.html", {"batch": batch, "form": form,
        "page": Paginator(questions, 20).get_page(request.GET.get("page")), "query": query})


@staff_member_required
@never_cache
@require_safe
def manage(request):
    require_batch_permission(request.user)
    batches = general_batches().annotate(question_count=Count("imported_questions__question", distinct=True)).order_by("-created_at", "-pk")
    return render(request, "general_question/manage.html", {"page": Paginator(batches, 25).get_page(request.GET.get("page"))})


@staff_member_required
@never_cache
@require_http_methods(["GET", "POST"])
def manage_batch(request, batch_id):
    require_batch_permission(request.user)
    batch = get_object_or_404(general_batches(), pk=batch_id)
    if request.method == "POST":
        try:
            payload = signing.loads(request.POST.get("snapshot", ""), salt=SALT, max_age=7200)
            if payload["batch_id"] != batch_id:
                raise signing.BadSignature
            count = transition_batch(batch_id, request.user, request.POST.get("action"), payload["fingerprint"])
        except (signing.BadSignature, KeyError):
            messages.error(request, "Review page expired or changed. Reload before submitting.")
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
        else:
            messages.success(request, f"{count} questions {'marked reviewed' if request.POST['action'] == 'review' else 'published'}.")
        return redirect("general_questions:manage_batch", batch_id=batch_id)
    questions = list(batch_questions(batch).select_related("current_revision", "subject", "topic"))
    snapshot = signing.dumps({"batch_id": batch_id, "fingerprint": fingerprint(questions)}, salt=SALT)
    return render(request, "general_question/manage_batch.html", {"batch": batch, "snapshot": snapshot,
        "total": len(questions), "page": Paginator(questions, 20).get_page(request.GET.get("page"))})
