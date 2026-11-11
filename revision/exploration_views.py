from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe
from .exploration import filter_related, load_node, path_links, question_paths, related_questions, taxonomy_path
from .exploration_forms import RelatedFilters
from .models import SavedQuestion
from .selectors import visible_questions, with_question_content


def source_question(request, question_id):
    return get_object_or_404(visible_questions(request.user).select_related("subject", "published_revision"), pk=question_id)


def source_saved(request, source):
    return SavedQuestion.objects.filter(user=request.user, question_id=source.pk).first() if source else None


@login_required
@never_cache
@require_safe
@transaction.atomic
def question_topics(request, question_id):
    get_user_model().objects.select_for_update().only("pk").get(pk=request.user.pk)
    source = source_question(request, question_id)
    parameters = {"from_question": source.pk}
    paths = question_paths(source.pk, parameters)
    return render(request, "revision/question_topics.html", {"source": source, "saved_source": source_saved(request, source),
        "paths": paths, "subject_path": path_links(taxonomy_path("subject", source.subject), parameters)})


@login_required
@never_cache
@require_safe
@transaction.atomic
def explore(request, kind, node_id):
    # Mock starts use this same user lock; no attempt is created mid-render.
    get_user_model().objects.select_for_update().only("pk").get(pk=request.user.pk)
    node = load_node(kind, node_id)
    source = None
    if "from_question" in request.GET:
        try:
            question_id = int(request.GET["from_question"])
        except (ValueError, TypeError):
            raise Http404
        source = source_question(request, question_id)
    parameters = {"from_question": source.pk} if source else {}
    context = {"kind": kind, "node": node, "source": source, "saved_source": source_saved(request, source),
               "breadcrumbs": path_links(taxonomy_path(kind, node), parameters)}
    try:
        base = related_questions(request.user, kind, node, source=source)
    except PermissionDenied:
        return render(request, "revision/explore_blocked.html", context, status=403)
    form = RelatedFilters(request.GET, questions=base)
    questions = base
    if form.is_valid():
        questions = filter_related(base, exam=form.cleaned_data["exam"], difficulty=form.cleaned_data["difficulty"])
    else:
        questions = base.none()
    questions = with_question_content(questions.annotate(is_saved=Exists(
        SavedQuestion.objects.filter(user=request.user, question_id=OuterRef("pk")))))
    page = Paginator(questions, 20).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "revision/explore.html", context | {"form": form, "page": page,
        "query": query.urlencode(), "source_query": f"?from_question={source.pk}" if source else ""})
