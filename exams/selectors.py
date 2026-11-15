"""Public taxonomy reads shared by HTML views and future adapters."""
from django.db.models import Prefetch

from .models import Exam, ExamAuthority, Subject, Topic


def topics_with_ancestry():
    """Load every supported label path without per-topic parent queries."""
    return Topic.objects.select_related(
        "subject", "part__subject", "module__subject", "module__part__subject",
        "chapter__subject", "chapter__part__subject", "chapter__module__subject",
        "chapter__module__part__subject",
    )


def subjects_for_exam(exam_id):
    """Reuse QuestionExam membership; subjects/chapters are shared across exams."""
    return Subject.objects.filter(questions__exam_associations__exam_id=exam_id).distinct()


def active_exams():
    return Exam.objects.filter(is_active=True, authority__is_active=True).select_related("authority")


def active_authorities():
    return ExamAuthority.objects.filter(is_active=True).prefetch_related(
        Prefetch("exams", queryset=active_exams(), to_attr="available_exams"),
    )
