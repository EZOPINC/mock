from django.conf import settings
from django.db import models


class SavedQuestion(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_questions")
    question = models.ForeignKey("questions.Question", on_delete=models.CASCADE, related_name="saved_by_users")
    saved_at = models.DateTimeField(auto_now_add=True)
    personal_note = models.TextField(blank=True, default="", max_length=10000)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_count = models.PositiveIntegerField(default=0)
    is_mastered = models.BooleanField(default=False)

    class Meta:
        ordering = ("-saved_at", "-pk")
        constraints = [models.UniqueConstraint(fields=("user", "question"), name="revision_user_question_unique")]


from practice.models import PracticeQuerySet, PracticeSession


class RevisionSessionManager(models.Manager.from_queryset(PracticeQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(kind="revision")


class RevisionSession(PracticeSession):
    """Revision-specific access to the shared Practice engine's frozen records."""
    objects = RevisionSessionManager()

    class Meta:
        proxy = True
        ordering = ("-started_at", "-pk")
