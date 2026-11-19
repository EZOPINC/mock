from django.db import migrations
from previous_year.appearance_input import appearance_identity, parse_appearance_tags


def backfill(apps, schema_editor):
    alias = schema_editor.connection.alias
    Record = apps.get_model("imports", "ImportedQuestion")
    Appearance = apps.get_model("previous_year", "QuestionAppearance")
    pending = []
    for question_id, metadata in Record.objects.using(alias).order_by().values_list(
            "question_id", "source_metadata").iterator(chunk_size=500):
        if not isinstance(metadata, dict):
            continue
        corrected = metadata.get("corrected") or {}
        original = metadata.get("original") or {}
        raw = corrected.get("previous_year_tags",
                            original.get("previous_year_tags", ""))
        if not isinstance(raw, str) or not raw:
            continue
        for edition in parse_appearance_tags(raw)[0]:
            pending.append(Appearance(question_id=question_id,
                           identity=appearance_identity(None, **edition), **edition))
            if len(pending) >= 500:
                Appearance.objects.using(alias).bulk_create(
                    pending, ignore_conflicts=True)
                pending.clear()
    if pending:
        Appearance.objects.using(alias).bulk_create(
            pending, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [
        ("imports", "0002_unified_import"),
        ("previous_year", "0003_question_appearances"),
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
