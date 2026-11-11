from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Case, Count, Q, When
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_POST, require_safe
from practice.models import PracticeQuestion
from practice.services import complete_session, progress, submit_answer
from practice.views import question_context
from .forms import BankFilters, RevisionStartForm
from .models import RevisionSession, SavedQuestion
from .selectors import bank_rows, filter_bank, valid_translations
from .sessions import start_revision


def own_session(request, session_id):
    return get_object_or_404(RevisionSession, pk=session_id, user=request.user)


def session_context(request, session, row):
    translations = valid_translations().filter(language__in=["en", "bn"]).order_by(Case(When(language="en", then=0), default=1), "pk")
    context = question_context(session, row, translations=translations)
    context.update({"is_revision": True,
        "answer_url": reverse("revision:answer", args=[session.pk, row.pk]),
        "saved_question": SavedQuestion.objects.filter(user=request.user, question_id=row.question_id).first()})
    return context


@login_required
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@csrf_protect
def start(request):
    parameters = request.POST if request.method == "POST" else request.GET
    form = RevisionStartForm(request.POST if request.method == "POST" else None,
                             initial=request.GET.dict(), user=request.user)
    if request.method == "POST":
        try:
            session = start_revision(request.user, request.POST)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            return redirect("revision:session", session_id=session.pk)
    filters = BankFilters(parameters, user=request.user)
    eligible_count = filter_bank(bank_rows(request.user), filters.cleaned_data).filter(content_available=True).count() if filters.is_valid() else 0
    return render(request, "revision/start.html", {"form": form, "eligible_count": eligible_count},
                  status=400 if request.method == "POST" else 200)


@login_required
@never_cache
@require_safe
def history(request):
    sessions = RevisionSession.objects.filter(user=request.user).annotate(total=Count("questions"),
        answered=Count("questions", filter=Q(questions__selected_answer__in=["A", "B", "C", "D"]))).order_by("-started_at", "-pk")
    return render(request, "revision/history.html", {"page": Paginator(sessions, 20).get_page(request.GET.get("page"))})


@login_required
@never_cache
@require_safe
def session_view(request, session_id):
    session = own_session(request, session_id)
    rows = list(session.questions.all())
    try:
        order = int(request.GET["question"]) if "question" in request.GET else None
    except (ValueError, TypeError):
        raise Http404
    row = next((row for row in rows if row.display_order == order), None) if order is not None else next((row for row in rows if not row.selected_answer), rows[0] if rows else None)
    if row is None:
        raise Http404
    return render(request, "revision/session.html", session_context(request, session, row))


@login_required
@never_cache
@require_POST
@csrf_protect
def answer(request, session_id, question_id):
    session = own_session(request, session_id)
    row = get_object_or_404(PracticeQuestion, pk=question_id, session=session)
    error, status = "", 200
    try:
        row = submit_answer(request.user, session.pk, row.pk, request.POST.get("answer"))
    except ValidationError as exception:
        error, status = "; ".join(exception.messages), 400
    session.refresh_from_db()
    context = session_context(request, session, row) | {"error": error}
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render(request, "revision/session_body.html", context, status=status)
    if error:
        return render(request, "revision/session.html", context, status=status)
    return redirect(reverse("revision:session", args=[session.pk]) + f"?question={row.display_order}#practice-question")


@login_required
@never_cache
@require_POST
@csrf_protect
def mastery(request, session_id, question_id):
    session = own_session(request, session_id)
    row = get_object_or_404(PracticeQuestion, session=session, pk=question_id)
    saved = get_object_or_404(SavedQuestion, user=request.user, question_id=row.question_id)
    action = request.POST.get("action")
    if action not in {"mastered", "needs_revision"}:
        raise Http404
    SavedQuestion.objects.filter(pk=saved.pk, user=request.user).update(is_mastered=action == "mastered")
    messages.success(request, "Revision status updated.")
    return redirect(reverse("revision:session", args=[session.pk]) + f"?question={row.display_order}#practice-question")


@login_required
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@csrf_protect
def finish(request, session_id):
    session = own_session(request, session_id)
    if request.method == "POST":
        if request.POST.get("confirm") != "yes":
            return render(request, "revision/finish.html", {"session": session, "error": "Confirm completion to finish this session."}, status=400)
        complete_session(request.user, session.pk)
        return redirect("revision:results", session_id=session.pk)
    return render(request, "revision/finish.html", {"session": session})


@login_required
@never_cache
@require_safe
def results(request, session_id):
    session = own_session(request, session_id)
    rows = list(session.questions.all())
    selected = [row for row in rows if row.is_correct is False] if request.GET.get("incorrect") == "1" else rows
    return render(request, "revision/results.html", {"session": session, "rows": selected,
        "incorrect_only": request.GET.get("incorrect") == "1", "progress": progress(rows)})
