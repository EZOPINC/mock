"""Pattern validation, distinct question selection and atomic attempt creation."""
from collections import Counter, deque
from copy import deepcopy
from decimal import Decimal
from secrets import SystemRandom

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import AttemptQuestion, ExamPattern, MockAttempt, MockSet, MockSetQuestion
from .execution import refresh_attempt
from .languages import default_reading_language, reading_language_options, validate_default_reading_language
from .rules import eligible_for_rule, rule_snapshot, section_rules, selection_tasks, validate_rule_layout


def eligible_question_ids(section):
    rules = section_rules(section)
    if rules:
        cache = {}
        return set().union(*(eligible_for_rule(rule, cache=cache) for rule in rules))
    from .languages import eligible_question_ids as eligible_ids
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
        validate_rule_layout(section)
    if sum(item.question_count for item in sections) != pattern.total_questions:
        raise ValidationError("Section question counts must equal the pattern total questions.")
    marks = sum((item.question_count * (item.positive_marks if item.positive_marks is not None else pattern.default_positive_marks) for item in sections), Decimal(0))
    if marks != pattern.total_marks:
        raise ValidationError("Section maximum marks must equal pattern total marks.")
    if check_availability:
        tasks = selection_tasks(sections, legacy_eligibility=eligible_question_ids)
        random = [task for task in tasks if task["manual"] is None]
        for task in random:
            if len(task["pool"]) < task["quota"].question_count:
                raise ValidationError(f"{task['quota']}: requires {task['quota'].question_count} eligible questions; only {len(task['pool'])} available.")
        if not _capacity_sufficient([task["quota"] for task in random], [task["pool"] for task in random]):
            raise ValidationError("Overlapping sections have insufficient distinct questions. A master question cannot be repeated.")
    return sections


@transaction.atomic
def activate_pattern(pattern):
    from exams.models import Exam
    exam_id = ExamPattern.objects.values_list("exam_id", flat=True).get(pk=pattern.pk)
    Exam.objects.select_for_update(no_key=True).get(pk=exam_id)
    pattern = ExamPattern.objects.select_for_update().get(pk=pattern.pk)
    sections = validate_configuration(pattern)
    validate_default_reading_language(pattern.exam, sections)
    if ExamPattern.objects.filter(exam_id=pattern.exam_id, stage_id=pattern.stage_id, status="active").exclude(pk=pattern.pk).exists():
        raise ValidationError("Deactivate the existing active pattern for this exam/stage first.")
    if pattern.is_free_demo:
        _check_demo_designation(pattern)
        _freeze_set(pattern)
    pattern.status = ExamPattern.Status.ACTIVE
    pattern.save(_transition=True)
    return pattern


@transaction.atomic
def deactivate_pattern(pattern):
    from exams.models import Exam
    exam_id = ExamPattern.objects.values_list("exam_id", flat=True).get(pk=pattern.pk)
    Exam.objects.select_for_update(no_key=True).get(pk=exam_id)
    pattern = ExamPattern.objects.select_for_update().get(pk=pattern.pk)
    pattern.status = ExamPattern.Status.INACTIVE
    pattern.save(_transition=True)
    return pattern


def available_patterns(**filters):
    candidates = ExamPattern.objects.filter(status=ExamPattern.Status.ACTIVE,
        exam__is_active=True, exam__authority__is_active=True, **filters).select_related(
            "exam__authority", "stage").prefetch_related("sections__subject", "sections__topic", "sections__selection_rules__manual_questions")
    result = []
    for pattern in candidates:
        try:
            validate_configuration(pattern, check_availability=not pattern.is_free_demo)
            if pattern.is_free_demo:
                _frozen_rows(pattern, lock=False)
        except ValidationError:
            continue
        result.append(pattern)
    return result


def select_questions(sections, *, pools=None):
    sections = list(sections)
    tasks = selection_tasks(sections, pools=pools, legacy_eligibility=eligible_question_ids)
    random = [task for task in tasks if task["manual"] is None]
    selection = _capacity_sufficient([task["quota"] for task in random], [task["pool"] for task in random], select=True)
    if selection is False:
        raise ValidationError("There are not enough distinct eligible questions. Please choose another test or try again later.")
    choices = iter(selection)
    result = {section.pk: [] for section in sections}
    for section in sections:
        section._rule_snapshot = []
    for task in tasks:
        ids = task["manual"] if task["manual"] is not None else next(choices)
        result[task["section"].pk].extend(ids)
        if task["rule"]:
            task["section"]._rule_snapshot.append(rule_snapshot(task["rule"], ids))
    return [result[section.pk] for section in sections]


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
            "selection_rules": getattr(section, "_rule_snapshot", []),
            "positive_marks": str(section.positive_marks if section.positive_marks is not None else pattern.default_positive_marks),
            "negative_marks": str(section.negative_marks if section.negative_marks is not None else pattern.default_negative_marks)} for section in sections],
    }


def _check_demo_designation(pattern):
    if ExamPattern.objects.filter(exam_id=pattern.exam_id, is_free_demo=True, status="active").exclude(pk=pattern.pk).exists():
        raise ValidationError("Retire the existing active Free Demo for this exam before publishing another.")


@transaction.atomic
def publish_free_demo(pattern):
    """Designate and activate a fixed publication, including an existing pattern."""
    from exams.models import Exam
    exam_id = ExamPattern.objects.values_list("exam_id", flat=True).get(pk=pattern.pk)
    Exam.objects.select_for_update(no_key=True).get(pk=exam_id)
    pattern = ExamPattern.objects.select_for_update().get(pk=pattern.pk)
    _check_demo_designation(pattern)
    sections = validate_configuration(pattern, check_availability=False)
    validate_default_reading_language(pattern.exam, sections)
    _freeze_set(pattern)
    pattern.is_free_demo = True
    pattern.save(_transition=True)
    return pattern if pattern.is_active else activate_pattern(pattern)


@transaction.atomic
def retire_free_demo(pattern):
    """Remove the designation, retaining its publication and all attempts."""
    from exams.models import Exam
    exam_id = ExamPattern.objects.values_list("exam_id", flat=True).get(pk=pattern.pk)
    Exam.objects.select_for_update(no_key=True).get(pk=exam_id)
    pattern = ExamPattern.objects.select_for_update().get(pk=pattern.pk)
    pattern.is_free_demo = False
    pattern.save(_transition=True)
    return pattern


def _select_locked_questions(pattern, sections):
    """Existing selector and eligibility locks, shared by publication and Premium."""
    from questions.models import Question, QuestionExam, QuestionTopic
    from exams.models import Topic
    candidate_ids = set().union(*(eligible_question_ids(section) for section in sections))
    list(Question.objects.select_for_update().filter(pk__in=candidate_ids).order_by("pk").values_list("pk", flat=True))
    list(Topic.objects.select_for_update().filter(pk__in=QuestionTopic.objects.filter(
        question_id__in=candidate_ids).values("topic_id")).order_by("pk").values_list("pk", flat=True))
    list(QuestionExam.objects.select_for_update().filter(question_id__in=candidate_ids,
        exam_id=pattern.exam_id).order_by("pk").values_list("pk", flat=True))
    pools = [eligible_question_ids(section) & candidate_ids for section in sections]
    selection = select_questions(sections, pools=pools)
    selected_ids = set().union(*selection)
    questions = {item.pk: item for item in Question.objects.filter(pk__in=selected_ids).select_related("published_revision")}
    return selection, questions


def _selected_rows(pattern, sections, selection, questions):
    rows = []
    for section, ids in zip(sections, selection):
        for pk in ids:
            question = questions[pk]
            rows.append(dict(section=section, question=question, question_revision=question.published_revision,
                display_order=len(rows) + 1,
                positive_marks=section.positive_marks if section.positive_marks is not None else pattern.default_positive_marks,
                negative_marks=section.negative_marks if section.negative_marks is not None else pattern.default_negative_marks))
    return rows


def _freeze_set(pattern):
    existing = MockSet.objects.filter(pattern=pattern).first()
    if existing:
        return existing
    sections = list(pattern.sections.select_for_update(of=("self",)).select_related("subject", "topic").order_by("display_order", "pk"))
    validate_configuration(pattern, sections, check_availability=False)
    selection, questions = _select_locked_questions(pattern, sections)
    rows = _selected_rows(pattern, sections, selection, questions)
    if len(rows) != pattern.total_questions:
        raise ValidationError("The shared question set is incomplete. No demo was published.")
    mock_set = MockSet(pattern=pattern, configuration=_configuration_snapshot(pattern, sections))
    mock_set.save(_publication=True)
    for values in rows:
        MockSetQuestion(mock_set=mock_set, **values).save(_publication=True)
    return mock_set


def _frozen_rows(pattern, *, lock=True):
    from questions.models import Question, QuestionExam
    from questions.eligibility import eligible_question_ids as published_eligible_ids
    mock_set = MockSet.objects.filter(pattern=pattern).first()
    if mock_set is None:
        raise ValidationError("Publish the shared Free Demo before starting it.")
    rows = list(mock_set.questions.select_related("section", "question", "question_revision"))
    ids = {row.question_id for row in rows}
    if lock:
        list(Question.objects.select_for_update().filter(pk__in=ids).order_by("pk").values_list("pk", flat=True))
        list(QuestionExam.objects.select_for_update().filter(question_id__in=ids, exam_id=pattern.exam_id).order_by("pk").values_list("pk", flat=True))
    if len(rows) != mock_set.configuration["total_questions"] or ids != published_eligible_ids(pattern.exam_id, question_ids=ids):
        raise ValidationError("The published Free Demo is currently unavailable. Please contact the administrator.")
    # Eligibility is rechecked against current publication/membership; actual
    # content remains bound to the previously approved frozen revisions.
    return mock_set, [dict(section=row.section, question=row.question, question_revision=row.question_revision,
        display_order=row.display_order, positive_marks=row.positive_marks, negative_marks=row.negative_marks) for row in rows]


@transaction.atomic
def start_attempt(user, pattern, *, language=None):
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    if not user.is_authenticated or not user.is_active:
        raise ValidationError("An active authenticated account is required.")
    if language not in {None, "", "en", "bn", "both"}:
        raise ValidationError("Choose English, Bengali or Both.")
    # Serialize repeated starts, including requests from separate tabs/devices.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    existing = MockAttempt.objects.filter(user=user, pattern_id=pattern.pk,
        status__in=[MockAttempt.Status.CREATED, MockAttempt.Status.IN_PROGRESS]).first()
    if existing:
        return refresh_attempt(user, existing.pk)
    pattern = ExamPattern.objects.select_for_update().get(pk=pattern.pk)
    if not pattern.is_active:
        raise ValidationError("This test is no longer available.")
    from billing.usage import reserve_mock
    is_free = reserve_mock(user, pattern)
    sections = list(pattern.sections.select_for_update(of=("self",)).select_related("subject", "topic").order_by("display_order", "pk"))
    validate_configuration(pattern, sections, check_availability=False)
    options = reading_language_options(sections)
    language = language or default_reading_language(pattern.exam, options)
    if language != "both" and all(code != language for code, _ in options):
        raise ValidationError("This language is unavailable across all sections of this mock.")
    mock_set = None
    if is_free:
        mock_set, rows = _frozen_rows(pattern)
        configuration = deepcopy(mock_set.configuration)
    else:
        selection, questions = _select_locked_questions(pattern, sections)
        rows = _selected_rows(pattern, sections, selection, questions)
        configuration = _configuration_snapshot(pattern, sections)
    if language in {"en", "bn"}:
        from questions.models import QuestionTranslation
        translated = set(QuestionTranslation.objects.filter(
            revision_id__in=[row["question_revision"].pk for row in rows], language=language
        ).values_list("question_id", flat=True))
        if not {row["question"].pk for row in rows} <= translated:
            raise ValidationError("This test does not have every question in the selected language. Choose another language or contact the administrator.")
    configuration["language"] = language
    attempt = MockAttempt(user=user, pattern=pattern, mock_set=mock_set, configuration=configuration)
    attempt.save(_assembly=True)
    for values in rows:
        AttemptQuestion(attempt=attempt, **values).save(_assembly=True)
    if len(rows) != pattern.total_questions:
        raise ValidationError("The question set is incomplete. No attempt was created.")
    attempt.status = MockAttempt.Status.IN_PROGRESS
    attempt.started_at = timezone.now()
    from datetime import timedelta
    attempt.expires_at = attempt.started_at + timedelta(minutes=attempt.configuration["duration_minutes"])
    attempt.save(_assembly=True, update_fields=["status", "started_at", "expires_at"])
    return attempt
