from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST, require_safe
from .forms import BankFilters, NoteForm
from .models import RevisionSession, SavedQuestion
from .selectors import bank_counts, bank_rows, filter_bank, hydrate_content, visible_questions

from django.contrib.auth.views import redirect_to_login
from django.http import Http404, JsonResponse
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from .services import set_saved


def return_path(request):
    value = request.POST.get("next", "")
    if value and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return value
    return reverse("accounts:learning_space")


@never_cache
@require_POST
@csrf_protect
def bookmark(request, question_id, saved):
    wants_json = "application/json" in request.headers.get("Accept", "")
    if not request.user.is_authenticated or not request.user.is_active:
        if wants_json:
            return JsonResponse({"error": "authentication_required"}, status=401)
        return redirect_to_login(return_path(request))
    try:
        state = set_saved(request.user, question_id, saved=saved)
    except Http404:
        if wants_json:
            return JsonResponse({"error": "question_not_found"}, status=404)
        raise
    return JsonResponse(state) if wants_json else redirect(return_path(request))




def own_saved(request, pk):
    return get_object_or_404(bank_rows(request.user), pk=pk)


def detail_context(request, saved, form=None):
    hydrate_content(request.user, [saved])
    return {"saved": saved, "question": saved.visible_question,
            "note_form": form if form is not None else NoteForm(instance=saved)}


@login_required
@never_cache
@require_safe
def dashboard(request):
    form = BankFilters(request.GET, user=request.user)
    rows = filter_bank(bank_rows(request.user), form.cleaned_data) if form.is_valid() else bank_rows(request.user).none()
    page = Paginator(rows, 20).get_page(request.GET.get("page"))
    hydrate_content(request.user, page.object_list)
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "revision/dashboard.html", {"form": form, "page": page,
        "counts": bank_counts(request.user), "query": query.urlencode(),
        "recent_sessions": RevisionSession.objects.filter(user=request.user)[:5]})


@login_required
@never_cache
@require_safe
def detail(request, pk):
    return render(request, "revision/detail.html", detail_context(request, own_saved(request, pk)))


@login_required
@never_cache
@require_POST
@csrf_protect
def manage(request, pk):
    saved = own_saved(request, pk)
    action = request.POST.get("action")
    own = SavedQuestion.objects.filter(pk=saved.pk, user=request.user)
    if action == "note":
        form = NoteForm(request.POST, instance=saved)
        if not form.is_valid():
            return render(request, "revision/detail.html", detail_context(request, saved, form), status=400)
        own.update(personal_note=form.cleaned_data["personal_note"])
        messages.success(request, "Personal note updated.")
    elif action in {"mastered", "needs_revision"}:
        own.update(is_mastered=action == "mastered")
        messages.success(request, "Revision status updated.")
    elif action == "reviewed":
        if not visible_questions(request.user).filter(pk=saved.question_id).exists():
            raise Http404
        own.update(reviewed_at=timezone.now(), review_count=F("review_count") + 1)
        messages.success(request, "Review recorded.")
    else:
        return JsonResponse({"error": "invalid_action"}, status=400)
    return redirect("revision:detail", pk=saved.pk)


@login_required
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
@csrf_protect
def remove(request, pk):
    saved = own_saved(request, pk)
    if request.method == "POST":
        if request.POST.get("confirm") != "yes":
            return render(request, "revision/remove.html", {"saved": saved, "error": "Confirm removal to continue."}, status=400)
        set_saved(request.user, saved.question_id, saved=False)
        messages.success(request, "Question removed from your Revision Bank.")
        return redirect("revision:dashboard")
    return render(request, "revision/remove.html", {"saved": saved})
