from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError


class RevisionWorkflowQuerySet(models.QuerySet):
    """Bulk writes bypass validation and locking; use the model or services."""

    def update(self, **kwargs):
        raise ValidationError(
            "Use question workflow services instead of bulk updates.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError(
            "Use question workflow services instead of bulk creation.")

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError(
            "Use question workflow services instead of bulk updates.")


class RevisionQuerySet(RevisionWorkflowQuerySet):
    def delete(self):
        raise ProtectedError("Question revisions must be retained.", self)


class Question(models.Model):
    class PublicationStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"

    class ReviewStatus(models.TextChoices):
        PENDING = "pending_review", "Pending review"
        REVIEWED = "reviewed", "Reviewed"

    source_question_id = models.CharField(
        max_length=200, blank=True, null=True)
    subject = models.ForeignKey(
        "exams.Subject", on_delete=models.PROTECT, related_name="questions")
    topic = models.ForeignKey("exams.Topic", on_delete=models.PROTECT,
                              related_name="questions", blank=True, null=True)
    publication_status = models.CharField(
        max_length=12, choices=PublicationStatus, default=PublicationStatus.DRAFT)
    review_status = models.CharField(
        max_length=14, choices=ReviewStatus, default=ReviewStatus.PENDING)
    current_revision = models.ForeignKey(
        "QuestionRevision", on_delete=models.PROTECT, related_name="working_for", blank=True, null=True, editable=False)
    published_revision = models.ForeignKey(
        "QuestionRevision", on_delete=models.PROTECT, related_name="published_for", blank=True, null=True, editable=False)
    exams = models.ManyToManyField(
        "exams.Exam", through="QuestionExam", related_name="questions")
    sources = models.ManyToManyField(
        "QuestionSource", through="QuestionSourceReference", related_name="questions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RevisionWorkflowQuerySet.as_manager()

    class Meta:
        ordering = ("-pk",)
        indexes = [models.Index(
            fields=("publication_status", "subject"), name="questions_public_subject_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(publication_status__in=[
                                   "draft", "published"]), name="questions_publication_valid"),
            models.CheckConstraint(condition=Q(review_status__in=[
                                   "pending_review", "reviewed"]), name="questions_review_valid"),
            models.CheckConstraint(condition=Q(publication_status="draft", published_revision__isnull=True) | Q(
                publication_status="published", published_revision__isnull=False), name="questions_public_pointer_valid"),
        ]

    def __str__(self):
        return f"Question {self.pk or '(new)'}"

    def clean(self):
        super().clean()
        if self.topic_id and self.subject_id and self.topic.subject_id != self.subject_id:
            raise ValidationError(
                {"topic": "Topic must belong to the selected subject."})
        for field in ("current_revision", "published_revision"):
            revision = getattr(self, field) if getattr(
                self, field + "_id") else None
            if revision and revision.question_id != self.pk:
                raise ValidationError(f"{field} must belong to this question.")
        if self.review_status == self.ReviewStatus.REVIEWED and not self.current_revision_id:
            raise ValidationError("Review requires a current revision.")
        if self.published_revision_id and not self.published_revision.published_at:
            raise ValidationError(
                "The published pointer must reference a published revision.")

    def save(self, *args, _workflow=False, **kwargs):
        with transaction.atomic():
            previous = type(self).objects.select_for_update().filter(
                pk=self.pk).first() if self.pk else None
            managed = ("current_revision_id", "published_revision_id",
                       "review_status", "publication_status")
            if not _workflow:
                if previous and any(getattr(self, f) != getattr(previous, f) for f in managed):
                    raise ValidationError(
                        "Use the revision, review, and publication services.")
                if not previous and (self.current_revision_id or self.published_revision_id or self.review_status != self.ReviewStatus.PENDING or self.publication_status != self.PublicationStatus.DRAFT):
                    raise ValidationError(
                        "New questions must start as pending-review drafts.")
            self.full_clean()
            return super().save(*args, **kwargs)


class QuestionRevision(models.Model):
    class Language(models.TextChoices):
        ENGLISH = "en", "English"
        BENGALI = "bn", "Bengali"

    class Answer(models.TextChoices):
        A = "A", "A"
        B = "B", "B"
        C = "C", "C"
        D = "D", "D"

    question = models.ForeignKey(
        Question, on_delete=models.PROTECT, related_name="revisions", db_index=False)
    revision_number = models.PositiveIntegerField()
    language = models.CharField(max_length=2, choices=Language)
    question_text = models.TextField()
    option_a = models.TextField()
    option_b = models.TextField()
    option_c = models.TextField()
    option_d = models.TextField()
    correct_answer = models.CharField(max_length=1, choices=Answer)
    explanation = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = RevisionQuerySet.as_manager()

    class Meta:
        ordering = ("question_id", "revision_number")
        constraints = [
            models.UniqueConstraint(
                fields=("question", "revision_number"), name="questions_revision_number_uniq"),
            models.CheckConstraint(condition=Q(
                revision_number__gt=0), name="questions_revision_positive"),
            models.CheckConstraint(condition=Q(
                language__in=["en", "bn"]), name="questions_language_valid"),
            models.CheckConstraint(condition=Q(correct_answer__in=[
                                   "A", "B", "C", "D"]), name="questions_answer_valid"),
            models.CheckConstraint(condition=~Q(question_text="") & ~Q(option_a="") & ~Q(
                option_b="") & ~Q(option_c="") & ~Q(option_d=""), name="questions_content_required"),
        ]

    def __str__(self):
        return f"Question {self.question_id}, revision {self.revision_number} ({self.language})"

    def clean(self):
        super().clean()
        for field in ("question_text", "option_a", "option_b", "option_c", "option_d"):
            if not getattr(self, field, "").strip():
                raise ValidationError({field: "This field cannot be blank."})
        if self.question_id:
            first = type(self).objects.filter(
                question_id=self.question_id).order_by("revision_number").first()
            if first and first.language != self.language:
                raise ValidationError(
                    {"language": "Language cannot change across revisions."})

    def save(self, *args, _publishing=False, **kwargs):
        with transaction.atomic():
            Question.objects.select_for_update().get(pk=self.question_id)
            previous = type(self).objects.filter(
                pk=self.pk).first() if self.pk else None
            if previous:
                # Content changes always create a new revision, including draft edits.
                changed = {f.attname for f in self._meta.concrete_fields if getattr(
                    self, f.attname) != getattr(previous, f.attname)}
                if changed and not (_publishing and changed == {"published_at"} and previous.published_at is None and self.published_at is not None):
                    raise ValidationError(
                        "Revisions are append-only. Create a new revision to edit content.")
            elif self.published_at is not None:
                raise ValidationError(
                    "New revisions cannot be published directly.")
            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ProtectedError("Question revisions must be retained.", [self])


class QuestionExam(models.Model):
    question = models.ForeignKey(
        Question, on_delete=models.PROTECT, related_name="exam_associations", db_index=False)
    exam = models.ForeignKey("exams.Exam", on_delete=models.PROTECT,
                             related_name="question_associations", db_index=False)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=("question", "exam"), name="questions_exam_pair_uniq")]
        indexes = [models.Index(
            fields=("exam", "question"), name="questions_exam_question_idx")]

    def __str__(self):
        return f"{self.question} / {self.exam}"


class QuestionSource(models.Model):
    source_name = models.CharField(max_length=200)
    source_document = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("source_name", "pk")

    def __str__(self):
        return f"{self.source_name}: {self.source_document}"


class QuestionSourceReference(models.Model):
    question = models.ForeignKey(
        Question, on_delete=models.PROTECT, related_name="source_references")
    source = models.ForeignKey(
        QuestionSource, on_delete=models.PROTECT, related_name="references")
    source_page = models.CharField(max_length=50, blank=True, null=True)
    source_question_number = models.CharField(
        max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.question} / {self.source}"
