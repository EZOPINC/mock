"""Read-only dashboard data from existing student-owned learning records."""
from decimal import Decimal

from django.db.models import Count, Q
from mock_tests.models import MockAttempt
from practice.models import PracticeQuestion, PracticeSession


def dashboard_context(user):
    attempts = MockAttempt.objects.filter(user=user)
    sessions = PracticeSession.objects.filter(user=user, kind="practice")
    mock_stats = attempts.aggregate(total=Count("pk"), finished=Count("pk", filter=Q(status__in=["submitted", "expired"])),
        open=Count("pk", filter=Q(status__in=["created", "in_progress"])))
    practice_stats = sessions.aggregate(total=Count("pk"), completed=Count("pk", filter=Q(status="completed")),
        open=Count("pk", filter=Q(status="in_progress")))
    answer_stats = PracticeQuestion.objects.filter(session__user=user, session__kind="practice").aggregate(
        answered=Count("pk", filter=Q(selected_answer__in=["A", "B", "C", "D"])),
        correct=Count("pk", filter=Q(is_correct=True)))
    accuracy = (Decimal(answer_stats["correct"]) * 100 / answer_stats["answered"]).quantize(Decimal("0.01")) if answer_stats["answered"] else None
    return {
        "mock_stats": mock_stats, "practice_stats": practice_stats,
        "practice_answer_stats": answer_stats, "practice_accuracy": accuracy,
        "recent_mock_attempts": list(attempts.annotate(question_count=Count("questions"),
            answered_count=Count("questions", filter=Q(questions__selected_answer__in=["A", "B", "C", "D"]))).order_by("-created_at", "-pk")[:5]),
        "recent_practice_sessions": list(sessions.annotate(question_count=Count("questions"),
            answered_count=Count("questions", filter=Q(questions__selected_answer__in=["A", "B", "C", "D"]))).order_by("-started_at", "-pk")[:5]),
    }
