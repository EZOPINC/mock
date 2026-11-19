"""Verify legacy revision text before retiring the compatibility columns."""
from django.db import migrations


def audit(connection):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                count(*) FILTER (WHERE t.id IS NULL),
                count(*) FILTER (
                    WHERE t.id IS NOT NULL AND
                    (t.question_text, t.option_a, t.option_b, t.option_c, t.option_d, t.explanation)
                    IS DISTINCT FROM
                    (r.question_text, r.option_a, r.option_b, r.option_c, r.option_d, r.explanation)
                ),
                count(*) FILTER (
                    WHERE t.id IS NULL AND (
                        r.question_text !~ '[^[:space:]]' OR r.option_a !~ '[^[:space:]]'
                        OR r.option_b !~ '[^[:space:]]' OR r.option_c !~ '[^[:space:]]'
                        OR r.option_d !~ '[^[:space:]]'
                    )
                )
            FROM questions_questionrevision r
            LEFT JOIN questions_questiontranslation t ON t.revision_id = r.id AND t.language = r.language
        """)
        missing, conflicts, invalid_legacy = cursor.fetchone()
        cursor.execute("""
            SELECT count(*)
            FROM questions_questiontranslation t
            JOIN questions_questionrevision r ON r.id = t.revision_id
            WHERE t.question_id <> r.question_id
                OR t.question_text !~ '[^[:space:]]' OR t.option_a !~ '[^[:space:]]'
                OR t.option_b !~ '[^[:space:]]' OR t.option_c !~ '[^[:space:]]'
                OR t.option_d !~ '[^[:space:]]'
        """)
        invalid_translations, = cursor.fetchone()
    return missing, conflicts, invalid_legacy, invalid_translations


def verify_and_backfill(apps, schema_editor):
    connection = schema_editor.connection
    missing, conflicts, invalid_legacy, invalid_translations = audit(connection)
    if conflicts or invalid_legacy or invalid_translations:
        raise RuntimeError(
            f"Translation audit failed: {conflicts} conflicting primary editions, "
            f"{invalid_legacy} incomplete legacy editions, {invalid_translations} invalid translations. "
            "Resolve these before retrying. Existing text was not overwritten."
        )
    if missing:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO questions_questiontranslation
                    (question_id, revision_id, language, question_text, option_a, option_b, option_c, option_d, explanation)
                SELECT r.question_id, r.id, r.language, r.question_text, r.option_a, r.option_b, r.option_c,
                    r.option_d, r.explanation
                FROM questions_questionrevision r
                WHERE NOT EXISTS (
                    SELECT 1 FROM questions_questiontranslation t
                    WHERE t.revision_id = r.id AND t.language = r.language
                )
                ON CONFLICT (revision_id, language) DO NOTHING
            """)
        if any(audit(connection)):
            raise RuntimeError("Translations changed during backfill. Retry the audit before applying this migration.")


class Migration(migrations.Migration):
    dependencies = [("questions", "0007_question_expiry")]
    operations = [migrations.RunPython(verify_and_backfill, migrations.RunPython.noop)]
