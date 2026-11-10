from django.db import migrations


FORWARD = """
CREATE FUNCTION exams_guard_taxonomy() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF TG_TABLE_NAME = 'exams_part' THEN
            IF OLD.subject_id IS DISTINCT FROM NEW.subject_id THEN
                RAISE EXCEPTION 'Existing parts cannot change subject' USING ERRCODE = '23514';
            END IF;
        ELSIF TG_TABLE_NAME = 'exams_module' THEN
            IF OLD.part_id IS DISTINCT FROM NEW.part_id THEN
                RAISE EXCEPTION 'Existing modules cannot change part' USING ERRCODE = '23514';
            END IF;
        ELSIF TG_TABLE_NAME = 'exams_chapter' THEN
            IF OLD.module_id IS DISTINCT FROM NEW.module_id THEN
                RAISE EXCEPTION 'Existing chapters cannot change module' USING ERRCODE = '23514';
            END IF;
        ELSIF TG_TABLE_NAME = 'exams_topic' THEN
            IF OLD.subject_id IS DISTINCT FROM NEW.subject_id THEN
                RAISE EXCEPTION 'Existing topics cannot change subject' USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'exams_topic' THEN
        IF NEW.chapter_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM exams_chapter c
            JOIN exams_module m ON m.id = c.module_id
            JOIN exams_part p ON p.id = m.part_id
            WHERE c.id = NEW.chapter_id AND p.subject_id = NEW.subject_id
        ) THEN
            RAISE EXCEPTION 'Topic chapter must belong to its subject' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER exams_part_parent_guard BEFORE UPDATE ON exams_part
FOR EACH ROW EXECUTE FUNCTION exams_guard_taxonomy();
CREATE TRIGGER exams_module_parent_guard BEFORE UPDATE ON exams_module
FOR EACH ROW EXECUTE FUNCTION exams_guard_taxonomy();
CREATE TRIGGER exams_chapter_parent_guard BEFORE UPDATE ON exams_chapter
FOR EACH ROW EXECUTE FUNCTION exams_guard_taxonomy();
CREATE TRIGGER exams_topic_hierarchy_guard BEFORE INSERT OR UPDATE ON exams_topic
FOR EACH ROW EXECUTE FUNCTION exams_guard_taxonomy();
"""

REVERSE = """
DROP TRIGGER exams_topic_hierarchy_guard ON exams_topic;
DROP TRIGGER exams_chapter_parent_guard ON exams_chapter;
DROP TRIGGER exams_module_parent_guard ON exams_module;
DROP TRIGGER exams_part_parent_guard ON exams_part;
DROP FUNCTION exams_guard_taxonomy();
"""


class Migration(migrations.Migration):
    dependencies = [("exams", "0002_chapter_module_part_topic_chapter_and_more")]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
