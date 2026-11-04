from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q, Value
from django.db.models.functions import Coalesce, Lower, Trim

from questions.models import Question, QuestionExam, QuestionRevision


class PaperWorkflowQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use paper model saves and publication services.")

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Use validated paper model saves.")

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError("Use validated paper model saves.")

    def delete(self):
        # Individual deletion also locks the paper and rejects published edits.
        with transaction.atomic():
            total, counts = 0, {}
            for obj in self.order_by("pk"):
                deleted, detail = obj.delete()
                total += deleted
                for key, value in detail.items():
                    counts[key] = counts.get(key, 0) + value
            return total, counts


class PreviousYearPaper(models.Model):
    exam = models.ForeignKey("exams.Exam", on_delete=models.PROTECT, related_name="previous_year_papers")
    stage = models.ForeignKey("exams.ExamStage", on_delete=models.PROTECT, related_name="previous_year_papers", null=True, blank=True)
    year = models.PositiveIntegerField()
    paper_name = models.CharField(max_length=200)
    part = models.CharField(max_length=100, null=True, blank=True)
    session = models.CharField(max_length=100, null=True, blank=True)
    is_published = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PaperWorkflowQuerySet.as_manager()

    class Meta:
        ordering = ("-year", "paper_name", "pk")
        indexes = [models.Index(fields=("exam", "-year"), name="previous_paper_exam_year_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(year__gt=0), name="previous_paper_year_positive"),
            models.CheckConstraint(condition=~Q(paper_name=""), name="previous_paper_name_required"),
            models.UniqueConstraint(
                F("exam"), Coalesce("stage", Value(0), output_field=models.BigIntegerField()),
                F("year"), Lower(Trim("paper_name")),
                Lower(Trim(Coalesce("part", Value("")))),
                Lower(Trim(Coalesce("session", Value("")))),
                name="previous_paper_identity_uniq",
            ),
        ]

    def __str__(self):
        return " — ".join(str(value) for value in (self.exam, self.year, self.paper_name, self.part, self.session) if value)

    def clean(self):
        super().clean()
        self.paper_name = self.paper_name.strip()
        self.part = (self.part or "").strip() or None
        self.session = (self.session or "").strip() or None
        if not self.paper_name:
            raise ValidationError({"paper_name": "Paper name is required."})
        if self.stage_id and self.exam_id and self.stage.exam_id != self.exam_id:
            raise ValidationError({"stage": "Stage must belong to the selected exam."})
        if self.pk and self.exam_id:
            original_exam = type(self).objects.filter(pk=self.pk).values_list("exam_id", flat=True).first()
            if original_exam and original_exam != self.exam_id:
                for row in self.paper_questions.select_related("question_revision__question"):
                    row.paper = self
                    try:
                        row.validate_association(require_current=False)
                    except ValidationError as error:
                        raise ValidationError({"exam": error.messages}) from error

    def save(self, *args, _publication=False, **kwargs):
        with transaction.atomic():
            previous = type(self).objects.select_for_update().filter(pk=self.pk).first() if self.pk else None
            if not _publication and self.is_published != (previous.is_published if previous else False):
                raise ValidationError("Use the paper publication services.")
            metadata = ("exam_id", "stage_id", "year", "paper_name", "part", "session")
            if previous and previous.is_published and not _publication and any(getattr(self, field) != getattr(previous, field) for field in metadata):
                raise ValidationError("Unpublish this paper before editing it.")
            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            paper = type(self).objects.select_for_update().get(pk=self.pk)
            if paper.is_published:
                raise ValidationError("Unpublish this paper before deleting it.")
            return super().delete(*args, **kwargs)


class PaperQuestion(models.Model):
    paper = models.ForeignKey(PreviousYearPaper, on_delete=models.PROTECT, related_name="paper_questions", db_index=False)
    question_revision = models.ForeignKey(QuestionRevision, on_delete=models.PROTECT, related_name="paper_questions")
    # Derived identity enables database uniqueness across different revisions.
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="paper_questions", editable=False)
    question_number = models.CharField(max_length=100)
    display_order = models.PositiveIntegerField()

    objects = PaperWorkflowQuerySet.as_manager()

    class Meta:
        ordering = ("display_order", "pk")
        constraints = [
            models.UniqueConstraint(fields=("paper", "display_order"), name="previous_paper_order_uniq"),
            models.UniqueConstraint(fields=("paper", "question_number"), name="previous_paper_number_uniq"),
            models.UniqueConstraint(fields=("paper", "question"), name="previous_paper_question_uniq"),
            models.CheckConstraint(condition=Q(display_order__gt=0), name="previous_order_positive"),
            models.CheckConstraint(condition=~Q(question_number=""), name="previous_number_required"),
        ]

    def __str__(self):
        return f"{self.paper}: {self.question_number}"

    def validate_association(self, *, require_current, allow_import_draft=False):
        revision = self.question_revision
        question = revision.question
        if allow_import_draft and not self.paper.is_published and question.publication_status == Question.PublicationStatus.DRAFT and question.review_status == Question.ReviewStatus.PENDING and question.current_revision_id == revision.pk and revision.published_at is None:
            if not QuestionExam.objects.filter(question_id=question.pk, exam_id=self.paper.exam_id).exists():
                raise ValidationError({"question_revision": "Question must be associated with this paper's exam."})
            return
        if question.publication_status != Question.PublicationStatus.PUBLISHED or revision.published_at is None:
            raise ValidationError({"question_revision": "Select a reviewed, published revision."})
        if require_current and question.published_revision_id != revision.pk:
            raise ValidationError({"question_revision": "Select the question's currently approved published revision."})
        if not QuestionExam.objects.filter(question_id=question.pk, exam_id=self.paper.exam_id).exists():
            raise ValidationError({"question_revision": "Question must be associated with this paper's exam."})

    def clean(self):
        super().clean()
        self.question_number = self.question_number.strip()
        if not self.question_number:
            raise ValidationError({"question_number": "Question number is required."})
        if self.question_revision_id and self.paper_id:
            self.question_id = self.question_revision.question_id
            previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
            changed = not previous or previous.question_revision_id != self.question_revision_id or previous.paper_id != self.paper_id
            self.validate_association(require_current=changed, allow_import_draft=getattr(self, "_allow_import_draft", False))
            if type(self).objects.filter(paper_id=self.paper_id, question_id=self.question_id).exclude(pk=self.pk).exists():
                raise ValidationError("This question is already associated with the paper.")

    def save(self, *args, _import_draft=False, **kwargs):
        self._allow_import_draft = _import_draft
        with transaction.atomic():
            old_paper_id = type(self).objects.filter(pk=self.pk).values_list("paper_id", flat=True).first() if self.pk else None
            papers = list(PreviousYearPaper.objects.select_for_update().filter(pk__in={self.paper_id, old_paper_id} - {None}).order_by("pk"))
            if any(paper.is_published for paper in papers):
                raise ValidationError("Unpublish the paper before changing its questions.")
            # Same lock order as Question Bank publication: paper, then question.
            if self.question_revision_id:
                revision = QuestionRevision.objects.get(pk=self.question_revision_id)
                Question.objects.select_for_update().get(pk=revision.question_id)
                # Clear potentially stale relation caches before validating.
                self.question_revision = QuestionRevision.objects.select_related("question").get(pk=revision.pk)
                self.question_id = revision.question_id
            if self.paper_id:
                self.paper = next(paper for paper in papers if paper.pk == self.paper_id)
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"question"}
            self.full_clean()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            paper = PreviousYearPaper.objects.select_for_update().get(pk=self.paper_id)
            if paper.is_published:
                raise ValidationError("Unpublish the paper before removing questions.")
            return super().delete(*args, **kwargs)
