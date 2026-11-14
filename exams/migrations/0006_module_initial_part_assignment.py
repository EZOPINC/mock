"""Allow only the first same-subject Part assignment on a direct Subject module."""
from importlib import import_module
from django.db import migrations


original = import_module("exams.migrations.0004_flexible_academic_taxonomy").FLEXIBLE_GUARDS
original = original.split("CREATE TRIGGER", 1)[0].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)
updated = original.replace(
    "IF OLD.part_id IS DISTINCT FROM NEW.part_id THEN",
    "IF OLD.part_id IS DISTINCT FROM NEW.part_id AND NOT (OLD.part_id IS NULL AND NEW.part_id IS NOT NULL) THEN",
    1,
)


class Migration(migrations.Migration):
    dependencies = [("exams", "0005_subject_display_order_topic_notes")]
    operations = [migrations.RunSQL(updated, reverse_sql=original)]
