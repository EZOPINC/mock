"""Authorize only an exact Module/old-Part/new-Part tuple in a transaction."""
from importlib import import_module
from django.db import migrations


original = import_module("exams.migrations.0009_chapter_initial_submodule_assignment").updated
old = "IF OLD.part_id IS DISTINCT FROM NEW.part_id AND NOT (OLD.part_id IS NULL AND NEW.part_id IS NOT NULL) THEN"
new = """IF OLD.part_id IS DISTINCT FROM NEW.part_id
               AND NOT (OLD.part_id IS NULL AND NEW.part_id IS NOT NULL)
               AND NOT (OLD.part_id IS NOT NULL AND NEW.part_id IS NOT NULL
                        AND current_setting('exams.module_part_reassignment', true)
                            IS NOT DISTINCT FROM concat(OLD.id, ':', OLD.part_id, ':', NEW.part_id)) THEN"""
assert original.count(old) == 1
updated = original.replace(old, new, 1)


class Migration(migrations.Migration):
    dependencies = [("exams", "0009_chapter_initial_submodule_assignment")]
    operations = [migrations.RunSQL(updated, reverse_sql=original)]
