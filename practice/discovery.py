"""Eligible master-question pools for hierarchical practice discovery."""
from django.core.exceptions import ValidationError

from exams.models import Part, Module, Chapter, Topic
from questions.eligibility import eligible_question_ids
from questions.models import Question, QuestionTopic


LEVELS = ("part", "module", "chapter", "topic")
MODELS = dict(zip(LEVELS, (Part, Module, Chapter, Topic)))


class PracticeTaxonomy:
    def __init__(self, exam, subject):
        self.subject = subject
        self.question_ids = eligible_question_ids(exam.pk, subject_id=subject.pk)
        self.nodes = {kind: {node.pk: node for node in model.objects.filter(subject=subject).order_by("name", "pk")}
                      for kind, model in MODELS.items()}
        self.pools = {kind: {} for kind in LEVELS}
        self.paths = {}
        for question_id, topic_id in QuestionTopic.objects.filter(question_id__in=self.question_ids).values_list("question_id", "topic_id"):
            if topic_id not in self.nodes["topic"]:
                continue
            for kind, node_id in self.ancestry("topic", topic_id).items():
                self.pools[kind].setdefault(node_id, set()).add(question_id)

    def ancestry(self, kind, node_id):
        key = (kind, node_id)
        if key not in self.paths:
            result = {kind: node_id}
            node = self.nodes[kind][node_id]
            parent = next((field for field in ("chapter", "module", "part") if getattr(node, field + "_id", None)), None)
            if parent:
                result.update(self.ancestry(parent, getattr(node, parent + "_id")))
            self.paths[key] = result
        return self.paths[key]

    def selected_ids(self, filters):
        chosen = {}
        for kind in LEVELS:
            node = filters.get(kind)
            if node is None:
                continue
            if not isinstance(node, MODELS[kind]) or node.pk not in self.nodes[kind]:
                raise ValidationError(f"Selected {kind} must belong to the selected subject.")
            chosen[kind] = node.pk
        if not chosen:
            return set(self.question_ids)
        deepest = next(kind for kind in reversed(LEVELS) if kind in chosen)
        path = self.ancestry(deepest, chosen[deepest])
        if any(path.get(kind) != node_id for kind, node_id in chosen.items()):
            raise ValidationError("Select a consistent taxonomy path. Intermediate levels may be skipped.")
        return set(self.pools[deepest].get(chosen[deepest], set()))

    def snapshot(self, filters):
        result = {}
        for kind in LEVELS:
            if filters.get(kind) is not None:
                node = self.nodes[kind][filters[kind].pk]
                result[kind] = {"id": node.pk, "code": node.code, "name": node.name}
        return result

    def options(self):
        # No stems, revision IDs, answers, or question IDs sent to the browser.
        return {kind: [{"id": node_id, "name": self.nodes[kind][node_id].name,
                        "count": len(pool), "ancestors": self.ancestry(kind, node_id)}
                       for node_id, pool in self.pools[kind].items()]
                for kind in LEVELS}


def configuration_matches(session, *, exam_id, subject_id, count, filters, difficulty=None):
    if session.kind != "practice":
        return False
    if session.configuration.get("difficulty") != difficulty:
        return False
    if (session.exam_id, session.subject_id, session.configuration["requested_count"]) != (exam_id, subject_id, str(count)):
        return False
    frozen = session.configuration.get("taxonomy_filters", {})
    for kind in LEVELS:
        expected = session.topic_id if kind == "topic" else frozen.get(kind, {}).get("id")
        value = filters.get(kind)
        submitted = getattr(value, "pk", value) or None
        if str(submitted) != str(expected):
            return False
    return True


def difficulty_pools(question_ids):
    """Group by published difficulty, never an unpublished working revision."""
    pools = {}
    for pk, value in Question.objects.filter(pk__in=question_ids).values_list("pk", "published_revision__difficulty_level"):
        key = (value or "").strip().casefold()
        pools.setdefault(key, set()).add(pk)
    return pools
