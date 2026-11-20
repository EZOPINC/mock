from importlib import import_module

from django.db import migrations, models


TEXT_FIELDS = ("explanation", "option_a", "option_b", "option_c", "option_d", "question_text")


def verify_primary_editions(apps, schema_editor):
    audit = import_module("questions.migrations.0008_verify_translation_snapshots").audit
    if any(audit(schema_editor.connection)):
        raise RuntimeError("Resolve missing or conflicting translation snapshots before removing revision text.")


def restore_primary_text(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            '''UPDATE questions_questionrevision r
               SET question_text = t.question_text, option_a = t.option_a, option_b = t.option_b,
                   option_c = t.option_c, option_d = t.option_d, explanation = t.explanation
               FROM questions_questiontranslation t
               WHERE t.revision_id = r.id AND t.question_id = r.question_id AND t.language = r.language'''
        )


class Migration(migrations.Migration):
    dependencies = [("questions", "0008_verify_translation_snapshots")]

    operations = [
        migrations.RunPython(verify_primary_editions, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="questionrevision", name="questions_content_required"),
        *[
            migrations.AlterField(model_name="questionrevision", name=field,
                                  field=models.TextField(null=True, blank=field == "explanation"))
            for field in TEXT_FIELDS
        ],
        migrations.RunPython(migrations.RunPython.noop, restore_primary_text),
        *[migrations.RemoveField(model_name="questionrevision", name=field) for field in TEXT_FIELDS],
    ]
