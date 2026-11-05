from datetime import timedelta
from decimal import Decimal
from django.db import migrations


def backfill(apps, schema_editor):
    Attempt = apps.get_model("mock_tests", "MockAttempt")
    Row = apps.get_model("mock_tests", "AttemptQuestion")
    alias = schema_editor.connection.alias
    for attempt in Attempt.objects.using(alias).exclude(started_at=None).iterator():
        attempt.expires_at = attempt.started_at + timedelta(minutes=attempt.configuration["duration_minutes"])
        fields = ["expires_at"]
        if attempt.status in {"submitted", "expired"}:
            rows = list(Row.objects.using(alias).filter(attempt_id=attempt.pk))
            sections = {}
            for section in attempt.configuration["sections"]:
                selected = [row for row in rows if row.section_id == section["id"]]
                sections[str(section["id"])] = {"name": section["name"], "correct": 0, "incorrect": 0,
                    "unanswered": len(selected), "score": "0", "maximum": str(sum((row.positive_marks for row in selected), Decimal(0)))}
            attempt.finalized_at = attempt.expires_at if attempt.status == "expired" else attempt.started_at
            attempt.total_score, attempt.maximum_score = Decimal(0), sum((row.positive_marks for row in rows), Decimal(0))
            attempt.correct_count, attempt.incorrect_count, attempt.unanswered_count = 0, 0, len(rows)
            attempt.section_results = sections
            fields += ["finalized_at", "total_score", "maximum_score", "correct_count", "incorrect_count", "unanswered_count", "section_results"]
            Row.objects.using(alias).filter(attempt_id=attempt.pk).update(awarded_marks=0)
        attempt.save(using=alias, update_fields=fields)


class Migration(migrations.Migration):
    dependencies = [("mock_tests", "0003_attemptquestion_answered_at_and_more")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
