from django.db import models

from imports.models import ImportBatch


class GeneralQuestionBatchManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(
            paper__isnull=True, status="completed",
            mapping_metadata__selection__import_type="general",
        )


class GeneralQuestionBatch(ImportBatch):
    """Admin-facing collection of existing General imports; no duplicate table."""
    objects = GeneralQuestionBatchManager()

    class Meta:
        proxy = True
        verbose_name = "General question batch"
        verbose_name_plural = "General question batches"
