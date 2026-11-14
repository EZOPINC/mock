"""Allow direct-subject chapters to receive their first same-subject module."""
from importlib import import_module

from django.db import migrations


original = import_module("exams.migrations.0006_module_initial_part_assignment").updated
updated = original.replace(
    "IF OLD.module_id IS DISTINCT FROM NEW.module_id OR OLD.part_id IS DISTINCT FROM NEW.part_id THEN",
    """IF (OLD.module_id IS DISTINCT FROM NEW.module_id OR OLD.part_id IS DISTINCT FROM NEW.part_id)
                AND NOT (OLD.module_id IS NULL AND OLD.part_id IS NULL
                         AND NEW.module_id IS NOT NULL AND NEW.part_id IS NULL) THEN""",
    1,
)


class Migration(migrations.Migration):
    dependencies = [("exams", "0006_module_initial_part_assignment")]
    operations = [migrations.RunSQL(updated, reverse_sql=original)]
