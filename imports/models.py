import uuid

from django.conf import settings
from django.db import models


class ImportBatch(models.Model):
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    filename = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64)
    context_sha256 = models.CharField(max_length=64)
    staging_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    mapping_version = models.CharField(max_length=30, default="unified-v2")
    status = models.CharField(max_length=20, default="completed", editable=False)
    row_count = models.PositiveIntegerField()
    error_count = models.PositiveIntegerField(default=0)
    paper = models.ForeignKey("previous_year.PreviousYearPaper", on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(auto_now_add=True)
    mapping_metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ("-created_at",)
        constraints = [models.UniqueConstraint(fields=("file_sha256", "context_sha256"), name="imports_file_context_unique")]

    def __str__(self):
        return f"Import {self.pk}: {self.filename}"


class ImportedQuestion(models.Model):
    batch = models.ForeignKey(ImportBatch, on_delete=models.PROTECT, related_name="imported_questions")
    source_row_number = models.PositiveIntegerField()
    question = models.ForeignKey("questions.Question", on_delete=models.PROTECT, related_name="import_records")
    action = models.CharField(max_length=20, default="created", editable=False)
    source_metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ("source_row_number",)
        constraints = [models.UniqueConstraint(fields=("batch", "source_row_number"), name="imports_batch_row_unique")]
