"""Allow first subdivision within a chapter's existing Module; never another Module."""
from importlib import import_module
from django.db import migrations


original = import_module("exams.migrations.0008_optional_submodule").updated
start = original.index("        ELSIF TG_TABLE_NAME = 'exams_chapter' THEN")
end = original.index("    parent_subject := NEW.subject_id;")
updated = original[:start] + """        ELSIF TG_TABLE_NAME = 'exams_chapter' THEN
            IF (OLD.submodule_id IS DISTINCT FROM NEW.submodule_id
                OR OLD.module_id IS DISTINCT FROM NEW.module_id OR OLD.part_id IS DISTINCT FROM NEW.part_id)
               AND NOT (
                   (OLD.submodule_id IS NULL AND OLD.module_id IS NULL AND OLD.part_id IS NULL
                    AND NEW.submodule_id IS NULL AND NEW.module_id IS NOT NULL AND NEW.part_id IS NULL)
                   OR
                   (OLD.submodule_id IS NULL AND OLD.module_id IS NOT NULL AND OLD.part_id IS NULL
                    AND NEW.submodule_id IS NOT NULL AND NEW.module_id IS NULL AND NEW.part_id IS NULL
                    AND EXISTS(SELECT 1 FROM exams_submodule s WHERE s.id=NEW.submodule_id AND s.module_id=OLD.module_id))
               ) THEN
                RAISE EXCEPTION 'Existing chapters cannot change parent' USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;
""" + original[end:]


class Migration(migrations.Migration):
    dependencies = [("exams", "0008_optional_submodule")]
    operations = [migrations.RunSQL(updated, reverse_sql=original)]
