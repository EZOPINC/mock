from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q


class PracticeQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use practice workflow services.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use practice workflow services.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Use practice workflow services.")

    def delete(self):
        raise ValidationError("Practice history must be retained.")


class PracticeSession(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        ABANDONED = "abandoned", "Abandoned"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="practice_sessions")
    exam = models.ForeignKey("exams.Exam", on_delete=models.PROTECT, related_name="practice_sessions")
    subject = models.ForeignKey("exams.Subject", on_delete=models.PROTECT, related_name="practice_sessions")
    topic = models.ForeignKey("exams.Topic", on_delete=models.PROTECT, null=True, blank=True, related_name="practice_sessions")
    start_token = models.UUIDField()
    configuration = models.JSONField()
    status = models.CharField(max_length=15, choices=Status, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    objects = PracticeQuerySet.as_manager()

    class Meta:
        ordering = ("-started_at", "-pk")
        indexes = [models.Index(fields=("user", "status", "-started_at"), name="practice_user_status_idx")]
        constraints = [
            models.UniqueConstraint(fields=("user", "start_token"), name="practice_start_token_unique"),
            models.CheckConstraint(condition=Q(status="in_progress", completed_at__isnull=True) | Q(status__in=["completed", "abandoned"], completed_at__isnull=False), name="practice_session_status_valid"),
        ]

    def __str__(self):
        return f"Practice {self.pk}: {self.configuration.get('exam_name', '')}"

    def clean(self):
        super().clean()
        # Validate new scope; a later taxonomy move must not block completion
        # of a session whose original classifications have already been frozen.
        if not self.pk and self.topic_id and self.topic.subject_id != self.subject_id:
            raise ValidationError("Topic must belong to the selected subject.")

    def save(self, *args, _assembly=False, _transition=False, **kwargs):
        if _assembly and not self.pk:
            self.full_clean()
            return super().save(*args, **kwargs)
        if _transition and self.pk:
            with transaction.atomic():
                previous = type(self).objects.select_for_update().get(pk=self.pk)
                if previous.status != self.Status.IN_PROGRESS or self.status not in {self.Status.COMPLETED, self.Status.ABANDONED}:
                    raise ValidationError("Practice sessions are locked after completion or abandonment.")
                for field in self._meta.concrete_fields:
                    if field.name not in {"status", "completed_at"} and getattr(previous, field.attname) != getattr(self, field.attname):
                        raise ValidationError("Session snapshots cannot change.")
                self.full_clean()
                return super().save(*args, **kwargs)
        raise ValidationError("Use the practice session services.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Practice history must be retained.")


class PracticeQuestion(models.Model):
    session = models.ForeignKey(PracticeSession, on_delete=models.PROTECT, related_name="questions")
    question = models.ForeignKey("questions.Question", on_delete=models.PROTECT, related_name="practice_questions")
    question_revision = models.ForeignKey("questions.QuestionRevision", on_delete=models.PROTECT, related_name="practice_questions")
    display_order = models.PositiveIntegerField()
    classification = models.JSONField(help_text="Frozen subject/topic labels for performance summaries.")
    selected_answer = models.CharField(max_length=1, blank=True, default="", choices=[(key, key) for key in "ABCD"])
    is_correct = models.BooleanField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    objects = PracticeQuerySet.as_manager()

    class Meta:
        ordering = ("display_order", "pk")
        constraints = [
            models.UniqueConstraint(fields=("session", "question"), name="practice_question_unique"),
            models.UniqueConstraint(fields=("session", "display_order"), name="practice_question_order_unique"),
            models.CheckConstraint(condition=Q(display_order__gt=0), name="practice_question_order_positive"),
            models.CheckConstraint(condition=Q(selected_answer="", is_correct__isnull=True, answered_at__isnull=True) | Q(selected_answer__in=["A", "B", "C", "D"], is_correct__isnull=False, answered_at__isnull=False), name="practice_answer_state_valid"),
        ]

    def clean(self):
        super().clean()
        if self.question_revision_id and (self.question_revision.question_id != self.question_id or self.question_revision.published_at is None):
            raise ValidationError("Select an approved revision belonging to this question.")
        if self.selected_answer and self.is_correct != (self.selected_answer == self.question_revision.correct_answer):
            raise ValidationError("Correctness must match the frozen revision answer.")

    def save(self, *args, _assembly=False, _feedback=False, **kwargs):
        with transaction.atomic():
            session = PracticeSession.objects.select_for_update().get(pk=self.session_id)
            if session.status != PracticeSession.Status.IN_PROGRESS:
                raise ValidationError("This practice session is closed.")
            if _assembly and not self.pk and not self.selected_answer:
                self.full_clean()
                return super().save(*args, **kwargs)
            if _feedback and self.pk:
                previous = type(self).objects.get(pk=self.pk)
                if previous.selected_answer:
                    raise ValidationError("Submitted answers are locked after feedback.")
                for field in self._meta.concrete_fields:
                    if field.name not in {"selected_answer", "is_correct", "answered_at"} and getattr(previous, field.attname) != getattr(self, field.attname):
                        raise ValidationError("Question snapshots cannot change.")
                if not self.selected_answer:
                    raise ValidationError("Select an answer before submitting.")
                self.full_clean()
                return super().save(*args, **kwargs)
            raise ValidationError("Use practice creation and answer services.")

    def delete(self, *args, **kwargs):
        raise ValidationError("Practice history must be retained.")
