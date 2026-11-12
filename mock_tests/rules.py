"""Rule eligibility and allocation tasks; reuse master eligibility checks."""
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db.models.functions import Lower, Trim

from exams.models import Topic
from .languages import eligible_question_ids
from questions.models import Question


FILTERS = ("subject", "part", "module", "chapter", "topic")


def section_rules(section):
    return list(section.selection_rules.all()) if section.pk else []


def validate_rule_layout(section, rules=None):
    rules = section_rules(section) if rules is None else list(rules)
    orders = set()
    for rule in rules:
        rule.section = section
        rule.full_clean(exclude=["section"], validate_unique=False, validate_constraints=False)
        if rule.display_order in orders:
            raise ValidationError("Rule display orders must be unique within a section.")
        orders.add(rule.display_order)
    if rules and sum(rule.question_count for rule in rules) != section.question_count:
        raise ValidationError(f"{section.name}: rule question counts must equal the section total ({section.question_count}).")
    return rules


def eligible_for_rule(rule, *, question_ids=None, cache=None):
    rule.clean()
    field = next(field for field in FILTERS if getattr(rule, field + "_id") is not None)
    node_id = getattr(rule, field + "_id")
    section = rule.section
    key = (section.pattern.exam_id, section.language_mode, field, node_id, rule.difficulty)
    if question_ids is None and cache is not None and key in cache:
        return cache[key]
    questions = Question.objects.filter(exam_associations__exam_id=section.pattern.exam_id, published_revision__isnull=False)
    if question_ids is not None:
        questions = questions.filter(pk__in=question_ids)
    if field == "subject":
        questions = questions.filter(subject_id=node_id)
    else:
        if field == "topic":
            topics = Topic.objects.filter(pk=node_id)
        elif field == "chapter":
            topics = Topic.objects.filter(chapter_id=node_id)
        elif field == "module":
            topics = Topic.objects.filter(Q(module_id=node_id) | Q(chapter__module_id=node_id))
        else:
            topics = Topic.objects.filter(Q(part_id=node_id) | Q(module__part_id=node_id)
                | Q(chapter__part_id=node_id) | Q(chapter__module__part_id=node_id))
        questions = questions.filter(topic_associations__topic_id__in=topics.values("pk"))
    if rule.difficulty:
        questions = questions.annotate(_difficulty=Lower(Trim("published_revision__difficulty_level")))
        questions = questions.filter(_difficulty__in=["", "unspecified"] if rule.difficulty == "unspecified" else [rule.difficulty])
    ids = questions.values_list("pk", flat=True).distinct()
    result = eligible_question_ids(section.pattern.exam_id, language_mode=section.language_mode, question_ids=ids)
    if question_ids is None and cache is not None:
        cache[key] = result
    return result


def selection_tasks(sections, *, pools=None, legacy_eligibility):
    tasks, cache, reserved = [], {}, set()
    for index, section in enumerate(sections):
        rules = validate_rule_layout(section)
        if not rules:
            pool = pools[index] if pools is not None else legacy_eligibility(section)
            tasks.append({"section": section, "rule": None, "quota": section, "pool": pool, "manual": None})
            continue
        for rule in sorted(rules, key=lambda item: (item.display_order, item.pk or 0)):
            pool = eligible_for_rule(rule, cache=cache)
            if pools is not None:
                pool = pool & pools[index]
            rows = list(rule.manual_questions.all())
            manual = None
            if rule.selection_mode == "manual":
                manual = [row.question_id for row in sorted(rows, key=lambda row: (row.display_order, row.pk))]
                if len(manual) != rule.question_count or len(set(manual)) != len(manual):
                    raise ValidationError(f"{rule}: select exactly {rule.question_count} distinct manual questions.")
                if not set(manual) <= pool:
                    raise ValidationError(f"{rule}: a manually selected question is no longer eligible.")
                if reserved & set(manual):
                    raise ValidationError("A question is manually selected in more than one rule or section.")
                reserved.update(manual)
            elif rows:
                raise ValidationError(f"{rule}: remove manual questions before using random selection.")
            if len(pool) < rule.question_count:
                raise ValidationError(f"{rule}: requires {rule.question_count} eligible questions; only {len(pool)} available.")
            tasks.append({"section": section, "rule": rule, "quota": rule, "pool": pool, "manual": manual})
    for task in tasks:
        if task["manual"] is None:
            task["pool"] = task["pool"] - reserved
    return tasks


def rule_snapshot(rule, selected_ids):
    field = next(field for field in FILTERS if getattr(rule, field + "_id") is not None)
    node = getattr(rule, field)
    return {"id": rule.pk, "display_order": rule.display_order, "filter_type": field,
        "filter_id": node.pk, "filter_code": node.code, "filter_name": node.name,
        "question_count": rule.question_count, "difficulty": rule.difficulty,
        "selection_mode": rule.selection_mode, "selected_question_ids": list(selected_ids)}
