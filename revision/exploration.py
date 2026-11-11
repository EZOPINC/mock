"""Bounded taxonomy navigation and related master-question discovery."""
from urllib.parse import urlencode
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Exists, OuterRef
from django.db.models.functions import Lower, Trim
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from exams.models import Subject, Part, Module, Chapter, Topic
from mock_tests.models import AttemptQuestion
from questions.models import QuestionExam, QuestionTopic
from .selectors import topic_scope, visible_questions

MODELS = {"subject": Subject, "part": Part, "module": Module, "chapter": Chapter, "topic": Topic}
# Bounded ancestor joins; only the requested node/path is loaded.
PARENTS = {"subject": (), "part": ("subject",), "module": ("subject", "part"),
    "chapter": ("subject", "module__part", "part"),
    "topic": ("subject", "chapter__module__part", "chapter__part", "module__part", "part")}


def node_queryset(kind):
    if kind not in MODELS:
        raise Http404
    return MODELS[kind].objects.select_related(*PARENTS[kind]) if PARENTS[kind] else MODELS[kind].objects.all()


def load_node(kind, node_id):
    return get_object_or_404(node_queryset(kind), pk=node_id)


def taxonomy_path(kind, node):
    """Walk only stored immediate parents, retaining skipped hierarchy levels."""
    subject = node if kind == "subject" else node.subject
    path = []
    while kind != "subject":
        path.append((kind, node))
        parent = next((field for field in node.parent_fields if getattr(node, field + "_id", None)), None)
        if parent is None:
            break
        node, kind = getattr(node, parent), parent
    path.append(("subject", subject))
    return list(reversed(path))


def path_links(path, parameters=None):
    query = urlencode(parameters or {})
    return [{"kind": kind, "node": node,
             "url": reverse("revision:explore", args=[kind, node.pk]) + ("?" + query if query else "")}
            for kind, node in path]


def question_paths(question_id, parameters=None):
    relations = ["topic__" + path for path in PARENTS["topic"]]
    tags = QuestionTopic.objects.filter(question_id=question_id).select_related("topic", *relations).order_by("-is_primary", "topic__name", "topic_id")
    return [{"primary": tag.is_primary, "topic": tag.topic,
             "path": path_links(taxonomy_path("topic", tag.topic), parameters)} for tag in tags]


def scoped_questions(questions, kind, node):
    if kind not in MODELS or not isinstance(node, MODELS[kind]):
        raise ValidationError("Select a valid taxonomy scope.")
    if kind == "subject":
        return questions.filter(subject_id=node.pk)
    tags = QuestionTopic.objects.filter(question_id=OuterRef("pk"), topic__in=topic_scope({kind: node}))
    return questions.filter(Exists(tags))


def scope_has_open_mock(user, kind, node):
    open_rows = AttemptQuestion.objects.filter(attempt__user=user, attempt__status__in=["created", "in_progress"])
    if kind == "subject":
        return open_rows.filter(question__subject_id=node.pk).exists()
    return open_rows.filter(question__topic_associations__topic__in=topic_scope({kind: node})).exists()


def related_questions(user, kind, node, *, source=None, exam=None, difficulty=None):
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied
    if kind not in MODELS or not isinstance(node, MODELS[kind]):
        raise ValidationError("Select a valid taxonomy scope.")
    # Protect direct/expanded links as well as the absence of controls in active mocks.
    if scope_has_open_mock(user, kind, node):
        raise PermissionDenied("Finish your open mock test before exploring this scope.")
    if source is not None and not visible_questions(user).filter(pk=source.pk).exists():
        raise Http404
    questions = scoped_questions(visible_questions(user), kind, node)
    if source is not None:
        questions = questions.exclude(pk=source.pk)
    return filter_related(questions, exam=exam, difficulty=difficulty)


def filter_related(questions, *, exam=None, difficulty=None):
    if exam is not None:
        membership = QuestionExam.objects.filter(question_id=OuterRef("pk"), exam=exam,
                                                exam__is_active=True, exam__authority__is_active=True)
        questions = questions.filter(Exists(membership))
    if difficulty is not None:
        questions = questions.annotate(_related_difficulty=Lower(Trim("published_revision__difficulty_level"))).filter(_related_difficulty=difficulty.strip().casefold())
    # EXISTS matches master rows without multiplying exam/translation/topic joins.
    return questions.order_by("pk")
