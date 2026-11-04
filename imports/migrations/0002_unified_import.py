import hashlib
import json

from django.db import migrations, models
import django.db.models.deletion


def backfill_contexts(apps, schema_editor):
    Batch = apps.get_model("imports", "ImportBatch")
    for batch in Batch.objects.using(schema_editor.connection.alias).select_related("paper").iterator():
        paper = batch.paper
        # Every pre-2.3B batch was a single-paper import. Reproduce the v2
        # canonical context without importing mutable application code.
        context = {"import_type": "previous_year", "exam_ids": [paper.exam_id], "exam_mapping": "selected",
                   "paper": {"exam_id": paper.exam_id, "stage_id": paper.stage_id, "year": paper.year}}
        for field in ("paper_name", "part", "session"):
            context["paper"][field] = (getattr(paper, field) or "").strip().casefold()
        batch.context_sha256 = hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        batch.save(update_fields=["context_sha256"])


class Migration(migrations.Migration):
    dependencies = [("imports", "0001_initial")]
    operations = [
        migrations.AlterField(model_name="importbatch", name="paper", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to="previous_year.previousyearpaper")),
        migrations.AddField(model_name="importbatch", name="context_sha256", field=models.CharField(default="", max_length=64), preserve_default=False),
        migrations.AlterField(model_name="importbatch", name="file_sha256", field=models.CharField(max_length=64)),
        migrations.AlterField(model_name="importbatch", name="mapping_version", field=models.CharField(default="unified-v2", max_length=30)),
        migrations.RunPython(backfill_contexts, migrations.RunPython.noop),
        migrations.AddConstraint(model_name="importbatch", constraint=models.UniqueConstraint(fields=("file_sha256", "context_sha256"), name="imports_file_context_unique")),
    ]
