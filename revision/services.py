"""Bookmark operations never load or return question content or assessment state."""
from django.core.exceptions import PermissionDenied
from django.http import Http404
from questions.services import published_questions
from mock_tests.models import AttemptQuestion
from practice.models import PracticeQuestion
from .models import SavedQuestion


def can_save(user, question_id):
    # Public question access, or a frozen question in this user's own session.
    return (published_questions().filter(pk=question_id, exams__is_active=True,
                exams__authority__is_active=True).exists()
            or AttemptQuestion.objects.filter(question_id=question_id, attempt__user=user).exists()
            or PracticeQuestion.objects.filter(question_id=question_id, session__user=user).exists())


def set_saved(user, question_id, *, saved):
    if not user.is_authenticated or not user.is_active:
        raise PermissionDenied("Sign in to save questions.")
    own = SavedQuestion.objects.filter(user=user, question_id=question_id)
    # Removing only the caller's record is safe even after unpublication/deletion.
    if saved:
        if not can_save(user, question_id):
            raise Http404
        SavedQuestion.objects.get_or_create(user=user, question_id=question_id)
    else:
        own.delete()
    return {"question_id": question_id, "saved": saved}


def attach_saved_state(user_id, rows):
    """One bookmark query for all visible questions; anonymous pages need none."""
    ids = {row.question_id for row in rows}
    saved = set(SavedQuestion.objects.filter(user_id=user_id, question_id__in=ids)
                .values_list("question_id", flat=True)) if user_id and ids else set()
    for row in rows:
        row.is_saved = row.question_id in saved
