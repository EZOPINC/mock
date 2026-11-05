"""Pattern validation, distinct question selection and atomic attempt creation."""
from collections import Counter, deque
from decimal import Decimal
from secrets import SystemRandom

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import AttemptQuestion, ExamPattern, MockAttempt
from .execution import refresh_attempt


def eligible_question_ids(section):
    from questions.eligibility import eligible_question_ids as eligible_ids
    return eligible_ids(section.pattern.exam_id, subject_id=section.subject_id,
        topic_id=section.topic_id, language_mode=section.language_mode)


def _capacity_sufficient(sections, pools, *, select=False):
    # Group questions with identical eligibility. Max flow handles overlapping
    # sections without greedy allocation starving more restrictive sections.
    membership = {}
    for index, pool in enumerate(pools):
        for pk in pool:
            membership.setdefault(pk, []).append(index)
    groups = Counter(tuple(indices) for indices in membership.values())
    graph = {}
    def edge(a, b, capacity):
        graph.setdefault(a, {})[b] = capacity
        graph.setdefault(b, {}).setdefault(a, 0)
    for index, section in enumerate(sections):
        edge("source", ("section", index), section.question_count)
    for number, (indices, count) in enumerate(groups.items()):
        node = ("pool", number)
        edge(node, "sink", count)
        for index in indices:
            edge(("section", index), node, count)
    flow = 0
    while True:
        parents = {"source": None}
        queue = deque(["source"])
        while queue and "sink" not in parents:
            node = queue.popleft()
            for target, capacity in graph.get(node, {}).items():
                if capacity > 0 and target not in parents:
                    parents[target] = node
                    queue.append(target)
        if "sink" not in parents:
            if flow != sum(section.question_count for section in sections):
                return False
            if not select:
                return True
            grouped_ids = {}
            for pk, indices in membership.items():
                grouped_ids.setdefault(tuple(indices), []).append(pk)
            chosen = [[] for section in sections]
            for number, indices in enumerate(groups):
                candidates = grouped_ids[indices]
                SystemRandom().shuffle(candidates)
                offset = 0
                for index in indices:
                    count = graph[("pool", number)][("section", index)]
                    chosen[index].extend(candidates[offset:offset + count])
                    offset += count
            for ids in chosen:
                SystemRandom().shuffle(ids)
            return chosen
        capacity, node = float("inf"), "sink"
        while parents[node] is not None:
            capacity = min(capacity, graph[parents[node]][node])
            node = parents[node]
        node = "sink"
        while parents[node] is not None:
            parent = parents[node]
            graph[parent][node] -= capacity
            graph[node][parent] += capacity
            node = parent
        flow += capacity


def validate_configuration(pattern, sections=None, *, check_availability=True):
    pattern.full_clean()
    if not pattern.exam.is_active or not pattern.exam.authority.is_active:
        raise ValidationError("The exam and authority must be active.")
    sections = list(pattern.sections.all()) if sections is None else list(sections)
    if not sections:
        raise ValidationError("Add at least one section.")
    orders = set()
    for section in sections:
        section.pattern = pattern
        section.full_clean(exclude=["pattern"], validate_unique=False, validate_constraints=False)
        if section.display_order in orders:
            raise ValidationError("Section display orders must be unique.")
        orders.add(section.display_order)
    if sum(item.question_count for item in sections) != pattern.total_questions:
        raise ValidationError("Section question counts must equal the pattern total questions.")
    marks = sum((item.question_count * (item.positive_marks if item.positive_marks is not None else pattern.default_positive_marks) for item in sections), Decimal(0))
    if marks != pattern.total_marks:
        raise ValidationError("Section maximum marks must equal pattern total marks.")
    if check_availability:
        pools = [eligible_question_ids(section) for section in sections]
        for section, pool in zip(sections, pools):
            if len(pool) < section.question_count:
                raise ValidationError(f"{section.name}: requires {section.question_count} eligible questions; only {len(pool)} available.")
        if not _capacity_sufficient(sections, pools):
            raise ValidationError("Overlapping sections have insufficient distinct questions. A master question cannot be repeated.")
    return sections


@transaction.atomic
def activate_pattern(pattern):
    from exams.models import Exam
    exam_id = ExamPattern.objects.values_list("exam_id", flat=True).get(pk=pattern.pk)
    Exam.objects.select_for_update().get(pk=exam_id)
    pattern = ExamPattern.objects.select_for_update().get(pk=pattern.pk)
    validate_configuration(pattern)
    if ExamPattern.objects.filter(exam_id=pattern.exam_id, stage_id=pattern.stage_id, status="active").exclude(pk=pattern.pk).exists():
        raise ValidationError("Deactivate the existing active pattern for this exam/stage first.")
    pattern.status = ExamPattern.Status.ACTIVE
    pattern.save(_transition=True)
    return pattern


@transaction.atomic
def deactivate_pattern(pattern):
    from exams.models import Exam
    exam_id = ExamPattern.objects.values_list("exam_id", flat=True).get(pk=pattern.pk)
    Exam.objects.select_for_update().get(pk=exam_id)
    pattern = ExamPattern.objects.select_for_update().get(pk=pattern.pk)
    pattern.status = ExamPattern.Status.INACTIVE
    pattern.save(_transition=True)
    return pattern


def available_patterns(**filters):
    candidates = ExamPattern.objects.filter(status=ExamPattern.Status.ACTIVE,
        exam__is_active=True, exam__authority__is_active=True, **filters).select_related(
            "exam__authority", "stage").prefetch_related("sections__subject", "sections__topic")
    result = []
    for pattern in candidates:
        try:
            validate_configuration(pattern)
        except ValidationError:
            continue
        result.append(pattern)
    return result


def select_questions(sections, *, pools=None):
    if pools is None:
        pools = [eligible_question_ids(section) for section in sections]
    selection = _capacity_sufficient(sections, pools, select=True)
    if selection is False:
        raise ValidationError("There are not enough distinct eligible questions. Please choose another test or try again later.")
    return selection


def _configuration_snapshot(pattern, sections):
    return {
        "name": pattern.name, "version": pattern.version,
        "exam_id": pattern.exam_id, "exam_name": pattern.exam.name,
        "authority_name": pattern.exam.authority.name,
        "stage_id": pattern.stage_id, "stage_name": pattern.stage.name if pattern.stage_id else "",
        "duration_minutes": pattern.duration_minutes, "total_questions": pattern.total_questions,
        "total_marks": str(pattern.total_marks), "default_positive_marks": str(pattern.default_positive_marks),
        "default_negative_marks": str(pattern.default_negative_marks),
        "sections": [{"id": section.pk, "name": section.name, "display_order": section.display_order,
            "question_count": section.question_count, "subject_id": section.subject_id, "topic_id": section.topic_id,
            "subject_name": section.subject.name if section.subject_id else "",
            "topic_name": section.topic.name if section.topic_id else "", "language_mode": section.language_mode,
            "positive_marks": str(section.positive_marks if section.positive_marks is not None else pattern.default_positive_marks),
            "negative_marks": str(section.negative_marks if section.negative_marks is not None else pattern.default_negative_marks)} for section in sections],
    }


@transaction.atomic
def start_attempt(user, pattern):
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from questions.models import Question
    if not user.is_authenticated or not user.is_active:
        raise ValidationError("An active authenticated account is required.")
    # Serialize repeated starts, including requests from separate tabs/devices.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    existing = MockAttempt.objects.filter(user=user, pattern_id=pattern.pk,
        status__in=[MockAttempt.Status.CREATED, MockAttempt.Status.IN_PROGRESS]).first()
    if existing:
        return refresh_attempt(user, existing.pk)
    pattern = ExamPattern.objects.select_for_update().get(pk=pattern.pk)
    if not pattern.is_active:
        raise ValidationError("This test is no longer available.")
    sections = list(pattern.sections.select_for_update(of=("self",)).select_related("subject", "topic").order_by("display_order", "pk"))
    validate_configuration(pattern, sections, check_availability=False)
    # Lock candidate masters before rechecking publication pointers and eligibility.
    candidate_ids = set().union(*(eligible_question_ids(section) for section in sections))
    list(Question.objects.select_for_update().filter(pk__in=candidate_ids).order_by("pk").values_list("pk", flat=True))
    # Restrict rechecked pools to locked masters, excluding newly published rows.
    pools = [eligible_question_ids(section) & candidate_ids for section in sections]
    selection = select_questions(sections, pools=pools)
    selected_ids = set().union(*selection)
    questions = {item.pk: item for item in Question.objects.filter(pk__in=selected_ids).select_related("published_revision")}
    attempt = MockAttempt(user=user, pattern=pattern, configuration=_configuration_snapshot(pattern, sections))
    attempt.save(_assembly=True)
    order = 0
    for section, ids in zip(sections, selection):
        for pk in ids:
            order += 1
            question = questions[pk]
            AttemptQuestion(attempt=attempt, section=section, question=question,
                question_revision=question.published_revision, display_order=order,
                positive_marks=section.positive_marks if section.positive_marks is not None else pattern.default_positive_marks,
                negative_marks=section.negative_marks if section.negative_marks is not None else pattern.default_negative_marks).save(_assembly=True)
    if order != pattern.total_questions:
        raise ValidationError("The question set is incomplete. No attempt was created.")
    attempt.status = MockAttempt.Status.IN_PROGRESS
    attempt.started_at = timezone.now()
    from datetime import timedelta
    attempt.expires_at = attempt.started_at + timedelta(minutes=attempt.configuration["duration_minutes"])
    attempt.save(_assembly=True, update_fields=["status", "started_at", "expires_at"])
    return attempt
