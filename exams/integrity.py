"""Read-only audit of current taxonomy links; historical snapshots are untouched."""
from django.db.models import Exists, F, OuterRef, Q, Subquery

from .models import Chapter, Module, Topic


def taxonomy_integrity_counts():
    from mock_tests.models import ExamPatternSection
    from practice.models import PracticeSession
    from questions.models import Question, QuestionTopic

    tags = QuestionTopic.objects.filter(question_id=OuterRef("pk"))
    primary = tags.filter(is_primary=True)
    questions = Question.objects.annotate(_has_tags=Exists(tags), _has_primary=Exists(primary),
        _primary_topic=Subquery(primary.values("topic_id")[:1]))
    invalid_primary = questions.filter(
        Q(_has_tags=True, _has_primary=False)
        | Q(topic__isnull=True, _has_tags=True)
        | Q(topic__isnull=False, _has_primary=False)
        | (Q(_has_primary=True) & ~Q(topic_id=F("_primary_topic")))
    )

    return {
        "question_tag_subject_mismatch": QuestionTopic.objects.exclude(topic__subject_id=F("question__subject_id")).count(),
        "question_primary_tag_mismatch": invalid_primary.count(),
        "module_part_subject_mismatch": Module.objects.filter(part__isnull=False).exclude(subject_id=F("part__subject_id")).count(),
        "chapter_module_subject_mismatch": Chapter.objects.filter(module__isnull=False).exclude(subject_id=F("module__subject_id")).count(),
        "chapter_part_subject_mismatch": Chapter.objects.filter(part__isnull=False).exclude(subject_id=F("part__subject_id")).count(),
        "topic_chapter_subject_mismatch": Topic.objects.filter(chapter__isnull=False).exclude(
            subject_id=F("chapter__subject_id")).count(),
        "topic_module_subject_mismatch": Topic.objects.filter(module__isnull=False).exclude(subject_id=F("module__subject_id")).count(),
        "topic_part_subject_mismatch": Topic.objects.filter(part__isnull=False).exclude(subject_id=F("part__subject_id")).count(),
        "question_topic_subject_mismatch": Question.objects.filter(topic__isnull=False).exclude(
            subject_id=F("topic__subject_id")).count(),
        "practice_topic_subject_mismatch": PracticeSession.objects.filter(topic__isnull=False).exclude(
            subject_id=F("topic__subject_id")).count(),
        "pattern_topic_subject_mismatch": ExamPatternSection.objects.filter(
            topic__isnull=False, subject__isnull=False).exclude(subject_id=F("topic__subject_id")).count(),
    }
