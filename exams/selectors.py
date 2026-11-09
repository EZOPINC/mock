"""Public taxonomy reads shared by HTML views and future adapters."""
from django.db.models import Prefetch

from .models import Exam, ExamAuthority


def active_exams():
    return Exam.objects.filter(is_active=True, authority__is_active=True).select_related("authority")


def active_authorities():
    return ExamAuthority.objects.filter(is_active=True).prefetch_related(
        Prefetch("exams", queryset=active_exams(), to_attr="available_exams"),
    )
