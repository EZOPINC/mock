"""Read-only audit of current taxonomy links; historical snapshots are untouched."""
from django.db.models import F

from .models import Topic


def taxonomy_integrity_counts():
    from mock_tests.models import ExamPatternSection
    from practice.models import PracticeSession
    from questions.models import Question

    return {
        "topic_chapter_subject_mismatch": Topic.objects.filter(chapter__isnull=False).exclude(
            subject_id=F("chapter__module__part__subject_id")).count(),
        "question_topic_subject_mismatch": Question.objects.filter(topic__isnull=False).exclude(
            subject_id=F("topic__subject_id")).count(),
        "practice_topic_subject_mismatch": PracticeSession.objects.filter(topic__isnull=False).exclude(
            subject_id=F("topic__subject_id")).count(),
        "pattern_topic_subject_mismatch": ExamPatternSection.objects.filter(
            topic__isnull=False, subject__isnull=False).exclude(subject_id=F("topic__subject_id")).count(),
    }
