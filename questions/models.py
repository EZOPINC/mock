from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.conf import settings
from django.core.validators import RegexValidator
from django.db.models.deletion import ProtectedError

TRANSLATED_FIELDS = ("question_text", "option_a", "option_b", "option_c", "option_d", "explanation")


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
    topics = models.ManyToManyField("exams.Topic", through="QuestionTopic", related_name="tagged_questions")
    publication_status = models.CharField(
        max_length=12, choices=PublicationStatus, default=PublicationStatus.DRAFT)
    review_status = models.CharField(
        max_length=14, choices=ReviewStatus, default=ReviewStatus.PENDING)
    correct_answer = models.CharField(max_length=1, choices=((key, key) for key in "ABCD"), blank=True, default="")
    difficulty_level = models.CharField(max_length=100, blank=True, default="")
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
            models.CheckConstraint(condition=Q(correct_answer__in=["", "A", "B", "C", "D"]), name="questions_master_answer_valid"),
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
        if self.pk and self.subject_id and self.topic_associations.exclude(topic__subject_id=self.subject_id).exists():
            raise ValidationError({"subject": "Remove existing topic tags before changing the question's subject."})
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
        if self.current_revision_id and (self.correct_answer != self.current_revision.correct_answer or self.difficulty_level != self.current_revision.difficulty_level):
            raise ValidationError("Shared answer and difficulty must match the working revision snapshot.")

    def save(self, *args, _workflow=False, **kwargs):
        with transaction.atomic():
            previous = type(self).objects.select_for_update().filter(
                pk=self.pk).first() if self.pk else None
            managed = ("current_revision_id", "published_revision_id",
                       "review_status", "publication_status", "correct_answer", "difficulty_level")
            if not _workflow:
                if previous and any(getattr(self, f) != getattr(previous, f) for f in managed):
                    raise ValidationError(
                        "Use the revision, review, and publication services.")
                if not previous and (self.current_revision_id or self.published_revision_id or self.review_status != self.ReviewStatus.PENDING or self.publication_status != self.PublicationStatus.DRAFT):
                    raise ValidationError(
                        "New questions must start as pending-review drafts.")
            self.full_clean()
            return super().save(*args, **kwargs)


class QuestionTopicQuerySet(RevisionWorkflowQuerySet):
    def delete(self):
        raise ValidationError("Use the question topic tagging services.")


class QuestionTopic(models.Model):
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="topic_associations", db_index=False)
    topic = models.ForeignKey("exams.Topic", on_delete=models.PROTECT, related_name="question_associations")
    is_primary = models.BooleanField(default=False)
    objects = QuestionTopicQuerySet.as_manager()

    class Meta:
        ordering = ("question_id", "-is_primary", "topic_id")
        constraints = [
            models.UniqueConstraint(fields=("question", "topic"), name="questions_topic_pair_unique"),
            models.UniqueConstraint(fields=("question",), condition=Q(is_primary=True), name="questions_one_primary_topic"),
        ]

    def clean(self):
        super().clean()
        if self.question_id and self.topic_id and self.topic.subject_id != self.question.subject_id:
            raise ValidationError({"topic": "Topic must belong to the question's subject."})
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values("question_id", "topic_id").first()
            if old and (old["question_id"], old["topic_id"]) != (self.question_id, self.topic_id):
                raise ValidationError("Existing topic associations cannot be moved; replace the tag instead.")

    def save(self, *args, **kwargs):
        from .tagging import save_tag
        return save_tag(self, *args, **kwargs)

    def delete(self, *args, **kwargs):
        from .tagging import delete_tag
        return delete_tag(self, *args, **kwargs)

    def __str__(self):
        return f"{self.question} / {self.topic}" + (" (primary)" if self.is_primary else "")


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
    language = models.CharField(max_length=35, choices=settings.QUESTION_LANGUAGES, validators=[RegexValidator(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")])
    question_text = models.TextField()
    option_a = models.TextField()
    option_b = models.TextField()
    option_c = models.TextField()
    option_d = models.TextField()
    correct_answer = models.CharField(max_length=1, choices=Answer)
    difficulty_level = models.CharField(max_length=100, blank=True, default="")
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
            models.CheckConstraint(condition=Q(language__regex=r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$"), name="questions_language_code_valid"),
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
            result = super().save(*args, **kwargs)
            if previous is None:
                QuestionTranslation(
                    question_id=self.question_id, revision=self, language=self.language,
                    **{field: getattr(self, field) for field in TRANSLATED_FIELDS},
                ).save(_assembly=True)
            return result

    def delete(self, *args, **kwargs):
        raise ProtectedError("Question revisions must be retained.", [self])


class QuestionTranslation(models.Model):
    """Immutable language content within a master Question revision snapshot."""
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="translations")
    revision = models.ForeignKey(QuestionRevision, on_delete=models.PROTECT, related_name="translations", db_index=False)
    language = models.CharField(max_length=35, choices=settings.QUESTION_LANGUAGES, validators=[RegexValidator(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")])
    question_text = models.TextField()
    option_a = models.TextField()
    option_b = models.TextField()
    option_c = models.TextField()
    option_d = models.TextField()
    explanation = models.TextField(blank=True)
    objects = RevisionQuerySet.as_manager()

    class Meta:
        ordering = ("language", "pk")
        constraints = [
            models.UniqueConstraint(fields=("revision", "language"), name="questions_translation_language_uniq"),
            models.CheckConstraint(condition=Q(language__regex=r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$"), name="questions_translation_code_valid"),
            models.CheckConstraint(condition=~Q(question_text="") & ~Q(option_a="") & ~Q(option_b="") & ~Q(option_c="") & ~Q(option_d=""), name="questions_translation_content"),
        ]

    def __str__(self):
        return f"Question {self.question_id}, revision {self.revision_id}, {self.language}"

    @property
    def correct_answer(self):
        return self.revision.correct_answer

    def clean(self):
        if self.revision_id and self.question_id != self.revision.question_id:
            raise ValidationError("Translation must belong to the revision's master Question.")
        for field in TRANSLATED_FIELDS[:-1]:
            if not getattr(self, field, "").strip():
                raise ValidationError({field: "This field cannot be blank."})
        if self.revision_id and self.language == self.revision.language:
            if any(getattr(self, field) != getattr(self.revision, field) for field in TRANSLATED_FIELDS):
                raise ValidationError("Primary translation must match the backward-compatible revision snapshot.")

    def save(self, *args, _assembly=False, **kwargs):
        with transaction.atomic():
            question = Question.objects.select_for_update().get(pk=self.question_id)
            if not _assembly or self.pk or self.revision.published_at or question.current_revision_id == self.revision_id:
                raise ValidationError("Use the translation revision service; translation snapshots are immutable.")
            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ProtectedError("Translation history must be retained.", [self])


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
