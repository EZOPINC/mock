from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.db.models.functions import Coalesce, Lower, Trim
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlencode
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_safe

from exams.models import Chapter, Module, Part, Subject, Submodule, Topic
from previous_year.models import PaperQuestion
from questions.difficulty import RATED_DIFFICULTIES
from questions.models import QuestionKind, QuestionTopic

from .review_forms import DIFFICULTY_FILTER_CHOICES, ReviewEditForm, ReviewFilters, SubjectReviewFilters
from .review_services import imported_questions, question_state, save_review_question, transition_selection
from .services import require_batch_permission

SESSION_KEY = "general_question_review_selection"
TOKEN_SALT = "general_question.review"
SELECTION_LIMIT = 200

SUBJECT_TAXONOMY = (
    ("Parts", "part", Part, ("part_id", "module__part_id", "chapter__part_id",
                             "chapter__module__part_id", "chapter__submodule__module__part_id")),
    ("Modules", "module", Module, ("module_id", "chapter__module_id", "chapter__submodule__module_id")),
    ("Submodules", "submodule", Submodule, ("chapter__submodule_id",)),
    ("Chapters", "chapter", Chapter, ("chapter_id",)),
    ("Topics", "topic", Topic, ("pk",)),
)


def taxonomy_counts(associations, ancestor, nodes):
    totals = dict(associations.annotate(ancestor_id=ancestor).filter(ancestor_id__isnull=False)
        .order_by().values("ancestor_id").annotate(total=Count("question_id", distinct=True))
        .values_list("ancestor_id", "total"))
    return [(node, totals.get(node.pk, 0)) for node in nodes]


def working_difficulty_condition(difficulty):
    if difficulty == "any":
        return Q(current_revision__isnull=False) & ~Q(review_difficulty__in=RATED_DIFFICULTIES)
    return Q(review_difficulty=difficulty)


def filter_working_difficulty(questions, difficulty):
    if not difficulty:
        return questions
    return questions.alias(review_difficulty=Lower(Trim("current_revision__difficulty_level"))).filter(
        working_difficulty_condition(difficulty))


def filter_review_classification(questions, data):
    for field, lookup in (("exam", "exams"), ("kind", "question_kind"), ("year", "paper_questions__paper__year")):
        if data[field]:
            questions = questions.filter(**{lookup: data[field]})
    if data["source"]:
        questions = questions.filter(paper_questions__isnull=data["source"] == "general")
    return filter_working_difficulty(questions, data["difficulty"])


def subject_counts(questions):
    return questions.order_by("subject__name", "subject_id").values("subject_id", "subject__name").annotate(total=Count("pk"))


@staff_member_required
@never_cache
@require_safe
def dashboard(request):
    require_batch_permission(request.user)
    questions = imported_questions().alias(
        review_difficulty=Lower(Trim("current_revision__difficulty_level")))
    difficulty_choices = DIFFICULTY_FILTER_CHOICES[1:]
    counts = questions.aggregate(total=Count("pk"), pending=Count("pk", filter=Q(review_status="pending_review")),
        drafts=Count("pk", filter=Q(publication_status="draft")), published=Count("pk", filter=Q(publication_status="published")),
        **{f"difficulty_{value}": Count("pk", filter=working_difficulty_condition(value)) for value, _ in difficulty_choices},
        **{f"kind_{value}": Count("pk", filter=Q(question_kind=value)) for value, _ in QuestionKind.choices})
    counts["general"] = questions.filter(paper_questions__isnull=True).count()
    counts["previous_year"] = counts["total"] - counts["general"]
    years = PaperQuestion.objects.filter(question_id__in=questions.order_by().values("pk")).values(
        "paper__year").annotate(total=Count("question_id", distinct=True)).order_by("-paper__year")
    subjects = subject_counts(questions)
    exams = questions.exclude(exams__isnull=True).order_by("exams__name", "exams__authority__name", "exams").values(
        "exams", "exams__name", "exams__authority__name").annotate(total=Count("pk", distinct=True))
    return render(request, "general_question/dashboard.html", {
        "counts": counts, "subjects": subjects, "exams": exams, "years": years,
        "difficulty_counts": [(value, label, counts[f"difficulty_{value}"]) for value, label in difficulty_choices],
        "kind_counts": [(value, label, counts[f"kind_{value}"]) for value, label in QuestionKind.choices],
    })


@staff_member_required
@never_cache
@require_safe
def review_subjects(request):
    require_batch_permission(request.user)
    return render(request, "general_question/review_subjects.html", {
        "subjects": subject_counts(imported_questions()),
    })


@staff_member_required
@never_cache
@require_safe
def review_subject(request, subject_id):
    require_batch_permission(request.user)
    subject = get_object_or_404(Subject, pk=subject_id)
    filters = SubjectReviewFilters(request.GET)
    parameters = {"subject": subject.pk}
    questions = imported_questions().filter(subject=subject)
    if filters.is_valid():
        data = filters.cleaned_data
        questions = filter_review_classification(questions, data)
        parameters.update({name: value for name, value in data.items() if value and name != "exam"})
        if data["exam"]:
            parameters["exam"] = data["exam"].pk
    else:
        questions = questions.none()
    counts = questions.aggregate(total=Count("pk", distinct=True),
        subject_only=Count("pk", filter=Q(topic_associations__isnull=True), distinct=True))
    associations = QuestionTopic.objects.filter(question_id__in=questions.order_by().values("pk"))
    sections = []
    for title, field, model, paths in SUBJECT_TAXONOMY:
        fields = [F(f"topic__{path}") for path in paths]
        ancestor = Coalesce(*fields) if len(fields) > 1 else fields[0]
        nodes = model.objects.filter(subject=subject).order_by("display_order", "name", "pk")
        rows = taxonomy_counts(associations, ancestor, nodes)
        sections.append({"title": title, "rows": [
            (node.name, count, queue_url("review_queue", urlencode(parameters | {field: node.pk})))
            for node, count in rows
        ]})
    return render(request, "general_question/review_subject.html", {
        "subject": subject, "filters": filters, "counts": counts, "sections": sections,
        "all_url": queue_url("review_queue", urlencode(parameters)),
        "subject_only_url": queue_url("review_queue", urlencode(parameters | {"subject_only": "1"})),
        "dashboard_url": reverse("general_questions:dashboard"),
    })


def review_filters(request, selected):
    form = ReviewFilters(request.GET)
    questions = imported_questions()
    if request.GET.get("selected") == "1":
        questions = questions.filter(pk__in=selected)
    if not form.is_valid():
        return form, questions.none()
    data = form.cleaned_data
    for field, lookup in (
        ("question_id", "pk"), ("subject", "subject"), ("batch", "import_records__batch_id"),
        ("review", "review_status"), ("publication", "publication_status"),
        ("language", "current_revision__translations__language"),
        ("text", "current_revision__translations__question_text__icontains"),
    ):
        if data[field]:
            questions = questions.filter(**{lookup: data[field]})
    if data["subject_only"]:
        questions = questions.filter(topic_associations__isnull=True)
    for _, field, _, paths in SUBJECT_TAXONOMY:
        if data[field]:
            match = Q()
            for path in paths:
                match |= Q(**{f"topic_associations__topic__{path}": data[field].pk})
            questions = questions.filter(match)
    return form, filter_review_classification(questions, data).distinct()


def queue_url(name, query, *args):
    url = reverse(f"general_questions:{name}", args=args)
    return f"{url}?{query}" if query else url


@staff_member_required
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def review_queue(request):
    require_batch_permission(request.user)
    selected = request.session.get(SESSION_KEY, {})
    parameters = request.GET.copy()
    parameters.pop("page", None)
    query = parameters.urlencode()
    if request.method == "POST":
        action = request.POST.get("selection_action")
        try:
            if action == "clear":
                selected = {}
            else:
                updated = transition_selection(request.user, selected, action)
                selected = updated if action == "review" else {}
                messages.success(request, f"{len(updated)} questions {'marked reviewed' if action == 'review' else 'published'}.")
            request.session[SESSION_KEY] = selected
        except ValidationError as error:
            messages.error(request, "; ".join(error.messages))
        return redirect(queue_url("review_queue", query))

    form, questions = review_filters(request, selected)
    page = Paginator(questions.select_related("subject", "current_revision").prefetch_related(
        "current_revision__translations").order_by("pk"), 35).get_page(request.GET.get("page"))
    return render(request, "general_question/review_queue.html", {
        "filters": form, "page": page, "query": query, "selected": selected,
        "selected_only": request.GET.get("selected") == "1", "selection_url": queue_url("review_queue", query),
    })


@staff_member_required
@never_cache
@require_http_methods(["GET", "HEAD", "POST"])
def review_question(request, question_id):
    require_batch_permission(request.user)
    selected = request.session.get(SESSION_KEY, {})
    form, questions = review_filters(request, selected)
    query = request.GET.urlencode()
    question = get_object_or_404(imported_questions().select_related("subject", "current_revision").prefetch_related(
        "current_revision__translations", "exams__authority", "source_references__source"), pk=question_id)
    question_key = str(question.pk)
    previous_id = questions.filter(pk__lt=question_id).order_by("-pk").values_list("pk", flat=True).first()
    next_id = questions.filter(pk__gt=question_id).order_by("pk").values_list("pk", flat=True).first()
    edit = None
    state = question_state(question)
    saved_token = signing.dumps({"question": question.pk, "user": request.user.pk, "state": state}, salt=TOKEN_SALT)
    if question.current_revision_id:
        action = request.POST.get("question_action")
        saving = request.method == "POST" and action in {"save", "save_next"}
        edit = ReviewEditForm(request.POST if saving else None, question=question)
        if request.method == "POST":
            try:
                payload = signing.loads(request.POST.get("revision_snapshot", ""), salt=TOKEN_SALT, max_age=7200)
                if payload != {"question": question.pk, "user": request.user.pk, "state": state}:
                    raise signing.BadSignature
                if saving and edit.is_valid():
                    save_review_question(request.user, question.pk, state, edit.cleaned_data)
                    selected.pop(question_key, None)
                    request.session[SESSION_KEY] = selected
                    messages.success(request, "Question saved. Inspect the saved version before selecting it for review.")
                    target = next_id if action == "save_next" and next_id else question.pk
                    return redirect(queue_url("review_question", query, target))
                if action == "select":
                    if question_key not in selected and len(selected) >= SELECTION_LIMIT:
                        raise ValidationError(f"Review or clear the current selection before adding more than {SELECTION_LIMIT} questions.")
                    selected[question_key] = state
                    request.session[SESSION_KEY] = selected
                    return redirect(queue_url("review_question", query, question.pk))
                if action == "remove":
                    selected.pop(question_key, None)
                    request.session[SESSION_KEY] = selected
                    return redirect(queue_url("review_question", query, question.pk))
            except signing.BadSignature:
                messages.error(request, "This review page changed or expired. Reload before submitting.")
                saved_token = request.POST.get("revision_snapshot", "")
            except ValidationError as error:
                if saving:
                    edit.add_error(None, error)
                else:
                    messages.error(request, "; ".join(error.messages))
                saved_token = request.POST.get("revision_snapshot", "")

    return render(request, "general_question/review_question.html", {
        "question": question, "edit": edit, "revision_snapshot": saved_token, "selected": selected,
        "filters": form, "selected_only": request.GET.get("selected") == "1", "query": query,
        "exam_appearances": question.exam_appearances.select_related("exam", "source_reference__source"),
        "is_selected": question_key in selected, "queue_url": queue_url("review_queue", query),
        "previous_url": queue_url("review_question", query, previous_id) if previous_id else None,
        "next_url": queue_url("review_question", query, next_id) if next_id else None,
    })
