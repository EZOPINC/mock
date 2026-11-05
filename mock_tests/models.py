from decimal import Decimal

from django.conf import settings

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F, Q


class ConfigurationQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use validated saves and pattern activation services.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use validated saves.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Use validated saves.")

    def delete(self):
        with transaction.atomic():
            count, details = 0, {}
            for obj in self.order_by("pk"):
                number, deleted = obj.delete()
                count += number
                for key, value in deleted.items():
                    details[key] = details.get(key, 0) + value
            return count, details


class ExamPattern(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    exam = models.ForeignKey("exams.Exam", on_delete=models.PROTECT, related_name="mock_patterns")
    stage = models.ForeignKey("exams.ExamStage", on_delete=models.PROTECT, null=True, blank=True, related_name="mock_patterns")
    name = models.CharField(max_length=200)
    version = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    duration_minutes = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    total_questions = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    total_marks = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    default_positive_marks = models.DecimalField(max_digits=8, decimal_places=2, default=1, validators=[MinValueValidator(Decimal("0.01"))])
    default_negative_marks = models.DecimalField(max_digits=8, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    status = models.CharField(max_length=10, choices=Status, default=Status.DRAFT, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ConfigurationQuerySet.as_manager()

    class Meta:
        ordering = ("exam", "name", "version", "pk")
        constraints = [
            models.UniqueConstraint(fields=("exam", "stage"), condition=Q(status="active", stage__isnull=False), name="mock_active_stage_unique"),
            models.UniqueConstraint(fields=("exam",), condition=Q(status="active", stage__isnull=True), name="mock_active_exam_unique"),
            models.CheckConstraint(condition=Q(duration_minutes__gt=0, total_questions__gt=0, version__gt=0, total_marks__gt=0, default_positive_marks__gt=0, default_negative_marks__gte=0), name="mock_pattern_values_valid"),
            models.CheckConstraint(condition=Q(status__in=["draft", "active", "inactive"]), name="mock_pattern_status_valid"),
        ]

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    def __str__(self):
        return f"{self.exam}: {self.name} (v{self.version})"

    def clean(self):
        super().clean()
        if not self.name.strip():
            raise ValidationError({"name": "A pattern name is required."})
        if self.stage_id and self.stage.exam_id != self.exam_id:
            raise ValidationError({"stage": "Stage must belong to the selected exam."})

    def save(self, *args, _transition=False, **kwargs):
        from exams.models import Exam
        with transaction.atomic():
            Exam.objects.select_for_update().get(pk=self.exam_id)
            previous = type(self).objects.select_for_update().filter(pk=self.pk).first() if self.pk else None
            if previous and previous.attempts.exists() and any(
                getattr(self, field.attname) != getattr(previous, field.attname)
                for field in self._meta.concrete_fields if field.name not in {"status"}
            ):
                raise ValidationError("This pattern has attempts. Create a new pattern version to change configuration.")
            if not _transition and (self.is_active or (previous and previous.is_active)):
                raise ValidationError("Deactivate the pattern before editing. Use the activation service to activate.")
            if not _transition and self.status != (previous.status if previous else self.Status.DRAFT):
                raise ValidationError("Use the pattern status services.")
            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            current = type(self).objects.select_for_update().get(pk=self.pk)
            if current.is_active:
                raise ValidationError("Deactivate the pattern before deleting.")
            return super().delete(*args, **kwargs)


class ExamPatternSection(models.Model):
    pattern = models.ForeignKey(ExamPattern, on_delete=models.PROTECT, related_name="sections")
    name = models.CharField(max_length=200)
    display_order = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    question_count = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    subject = models.ForeignKey("exams.Subject", on_delete=models.PROTECT, null=True, blank=True)
    topic = models.ForeignKey("exams.Topic", on_delete=models.PROTECT, null=True, blank=True)
    language_mode = models.CharField(max_length=5, choices=[("en", "English"), ("bn", "Bengali"), ("mixed", "English/Bengali")], default="mixed")
    positive_marks = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0.01"))], help_text="Blank uses the pattern default.")
    negative_marks = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)], help_text="Nonnegative deduction; blank uses the pattern default. Unanswered questions score zero.")
    objects = ConfigurationQuerySet.as_manager()

    class Meta:
        ordering = ("display_order", "pk")
        constraints = [
            models.UniqueConstraint(fields=("pattern", "display_order"), name="mock_section_order_unique"),
            models.CheckConstraint(condition=Q(question_count__gt=0, display_order__gt=0), name="mock_section_counts_valid"),
            models.CheckConstraint(condition=Q(positive_marks__isnull=True) | Q(positive_marks__gt=0), name="mock_section_positive_valid"),
            models.CheckConstraint(condition=Q(negative_marks__isnull=True) | Q(negative_marks__gte=0), name="mock_section_penalty_valid"),
            models.CheckConstraint(condition=Q(language_mode__in=["en", "bn", "mixed"]), name="mock_section_language_valid"),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if not self.name.strip():
            raise ValidationError({"name": "A section name is required."})
        if self.topic_id and self.subject_id and self.topic.subject_id != self.subject_id:
            raise ValidationError({"topic": "Topic must belong to the selected subject."})

    def save(self, *args, **kwargs):
        with transaction.atomic():
            ids = {self.pattern_id}
            if self.pk:
                ids.add(type(self).objects.get(pk=self.pk).pattern_id)
            if any(pattern.is_active or pattern.attempts.exists() for pattern in ExamPattern.objects.select_for_update().filter(pk__in=ids).order_by("pk")):
                raise ValidationError("Active or previously used patterns cannot change sections. Create a new pattern version.")
            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            pattern = ExamPattern.objects.select_for_update().get(pk=self.pattern_id)
            if pattern.is_active or pattern.attempts.exists():
                raise ValidationError("Active or previously used patterns cannot delete sections.")
            return super().delete(*args, **kwargs)


class AttemptQuerySet(ConfigurationQuerySet):
    def delete(self):
        raise ValidationError("Attempts and their fixed question sets must be retained.")


class MockAttempt(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        IN_PROGRESS = "in_progress", "In Progress"
        SUBMITTED = "submitted", "Submitted"
        EXPIRED = "expired", "Expired"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="mock_attempts")
    pattern = models.ForeignKey(ExamPattern, on_delete=models.PROTECT, related_name="attempts")
    status = models.CharField(max_length=15, choices=Status, default=Status.CREATED)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    configuration = models.JSONField(help_text="Immutable configuration snapshot; no answer keys.")
    expires_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    last_position = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    save_version = models.PositiveBigIntegerField(default=0)
    last_save_token = models.UUIDField(null=True, blank=True)
    total_score = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    maximum_score = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    correct_count = models.PositiveIntegerField(null=True, blank=True)
    incorrect_count = models.PositiveIntegerField(null=True, blank=True)
    unanswered_count = models.PositiveIntegerField(null=True, blank=True)
    section_results = models.JSONField(default=dict, blank=True)
    objects = AttemptQuerySet.as_manager()

    @property
    def is_finalized(self):
        return self.status in {self.Status.SUBMITTED, self.Status.EXPIRED}

    @property
    def percentage(self):
        return (self.total_score * 100 / self.maximum_score).quantize(Decimal("0.01")) if self.maximum_score else Decimal(0)

    class Meta:
        ordering = ("-created_at", "-pk")
        indexes = [models.Index(fields=("user", "-created_at"), name="mock_attempt_user_created_idx"), models.Index(fields=("status", "expires_at"), name="mock_attempt_expiry_idx")]
        constraints = [
            models.UniqueConstraint(fields=("user", "pattern"), condition=Q(status__in=["created", "in_progress"]), name="mock_attempt_one_open_unique"),
            models.CheckConstraint(condition=Q(status__in=["created", "in_progress", "submitted", "expired"]), name="mock_attempt_status_valid"),
            models.CheckConstraint(condition=Q(status="created", started_at__isnull=True) | Q(status__in=["in_progress", "submitted", "expired"], started_at__isnull=False), name="mock_attempt_start_valid"),
            models.CheckConstraint(condition=Q(started_at__isnull=True, expires_at__isnull=True) | Q(started_at__isnull=False, expires_at__isnull=False, expires_at__gt=F("started_at")), name="mock_attempt_deadline_valid"),
            models.CheckConstraint(condition=Q(last_position__gt=0), name="mock_attempt_position_valid"),
            models.CheckConstraint(condition=Q(status__in=["created", "in_progress"], finalized_at__isnull=True, total_score__isnull=True, maximum_score__isnull=True, correct_count__isnull=True, incorrect_count__isnull=True, unanswered_count__isnull=True) | Q(status__in=["submitted", "expired"], finalized_at__isnull=False, total_score__isnull=False, maximum_score__isnull=False, maximum_score__gt=0, correct_count__isnull=False, incorrect_count__isnull=False, unanswered_count__isnull=False), name="mock_attempt_final_values"),
        ]

    def __str__(self):
        return f"Attempt {self.pk}: {self.configuration.get('name', '')}"

    def save(self, *args, _assembly=False, _execution=False, **kwargs):
        if _execution:
            with transaction.atomic():
                previous = type(self).objects.select_for_update().get(pk=self.pk)
                if previous.is_finalized or previous.status != self.Status.IN_PROGRESS:
                    raise ValidationError("Finalized attempts cannot change.")
                mutable = {"status", "finalized_at", "last_position", "save_version", "last_save_token", "total_score", "maximum_score", "correct_count", "incorrect_count", "unanswered_count", "section_results"}
                if any(getattr(previous, field.attname) != getattr(self, field.attname) for field in self._meta.concrete_fields if field.name not in mutable):
                    raise ValidationError("Attempt configuration is immutable.")
                if self.status not in {self.Status.IN_PROGRESS, self.Status.SUBMITTED, self.Status.EXPIRED}:
                    raise ValidationError("Invalid attempt transition.")
                self.full_clean()
                return super().save(*args, **kwargs)
        if not _assembly:
            raise ValidationError("Use the attempt creation service; attempt snapshots are immutable.")
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if previous:
            if previous.status != self.Status.CREATED or self.status != self.Status.IN_PROGRESS:
                raise ValidationError("Attempt snapshots cannot be edited.")
            for field in self._meta.concrete_fields:
                if field.name not in {"status", "started_at", "expires_at"} and getattr(previous, field.attname) != getattr(self, field.attname):
                    raise ValidationError("Attempt snapshots cannot be edited.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Attempts must be retained.")


class AttemptQuestion(models.Model):
    attempt = models.ForeignKey(MockAttempt, on_delete=models.PROTECT, related_name="questions")
    section = models.ForeignKey(ExamPatternSection, on_delete=models.PROTECT, related_name="attempt_questions")
    question = models.ForeignKey("questions.Question", on_delete=models.PROTECT, related_name="mock_attempt_questions")
    question_revision = models.ForeignKey("questions.QuestionRevision", on_delete=models.PROTECT, related_name="mock_attempt_questions")
    display_order = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    positive_marks = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    negative_marks = models.DecimalField(max_digits=8, decimal_places=2, validators=[MinValueValidator(0)])
    selected_answer = models.CharField(max_length=1, blank=True, default="", choices=[(value, value) for value in "ABCD"])
    marked_for_review = models.BooleanField(default=False)
    answered_at = models.DateTimeField(null=True, blank=True)
    awarded_marks = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    objects = AttemptQuerySet.as_manager()

    class Meta:
        ordering = ("display_order", "pk")
        constraints = [
            models.UniqueConstraint(fields=("attempt", "display_order"), name="mock_attempt_question_order_uniq"),
            models.UniqueConstraint(fields=("attempt", "question"), name="mock_attempt_question_uniq"),
            models.CheckConstraint(condition=Q(display_order__gt=0, positive_marks__gt=0, negative_marks__gte=0), name="mock_attempt_question_values"),
            models.CheckConstraint(condition=Q(selected_answer__in=["", "A", "B", "C", "D"]), name="mock_attempt_option_valid"),
        ]

    def clean(self):
        super().clean()
        if self.section_id and self.attempt_id and self.section.pattern_id != self.attempt.pattern_id:
            raise ValidationError("Section must belong to the attempt's pattern.")
        if self.question_revision_id and self.question_id != self.question_revision.question_id:
            raise ValidationError("Revision must belong to the selected master question.")
        if self.question_revision_id and self.question_revision.published_at is None:
            raise ValidationError("Attempt questions require an approved published revision.")

    def save(self, *args, _assembly=False, _execution=False, **kwargs):
        if _execution:
            with transaction.atomic():
                attempt = MockAttempt.objects.select_for_update().get(pk=self.attempt_id)
                if attempt.status != MockAttempt.Status.IN_PROGRESS:
                    raise ValidationError("Answers are locked after finalization.")
                previous = type(self).objects.get(pk=self.pk)
                mutable = {"selected_answer", "marked_for_review", "answered_at", "awarded_marks"}
                if any(getattr(previous, field.attname) != getattr(self, field.attname) for field in self._meta.concrete_fields if field.name not in mutable):
                    raise ValidationError("Attempt question snapshots cannot change.")
                self.full_clean()
                return super().save(*args, **kwargs)
        if not _assembly or self.pk or self.attempt.status != MockAttempt.Status.CREATED:
            raise ValidationError("The attempt question set is fixed. Use the attempt creation service.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Attempt questions must be retained.")
