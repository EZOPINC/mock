from django.db import migrations


SQL = """
CREATE FUNCTION mock_guard_published_set() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Published Mock sets and their question rows are immutable' USING ERRCODE = '23514';
END;
$$;
CREATE TRIGGER mock_set_immutable BEFORE UPDATE OR DELETE ON mock_tests_mockset
FOR EACH ROW EXECUTE FUNCTION mock_guard_published_set();
CREATE TRIGGER mock_set_question_immutable BEFORE UPDATE OR DELETE ON mock_tests_mocksetquestion
FOR EACH ROW EXECUTE FUNCTION mock_guard_published_set();

CREATE FUNCTION mock_guard_frozen_pattern() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM mock_tests_mockset WHERE pattern_id = OLD.id) AND
       to_jsonb(OLD) - ARRAY['status','is_free_demo'] <> to_jsonb(NEW) - ARRAY['status','is_free_demo'] THEN
        RAISE EXCEPTION 'Published pattern configuration is frozen' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER mock_frozen_pattern BEFORE UPDATE ON mock_tests_exampattern
FOR EACH ROW EXECUTE FUNCTION mock_guard_frozen_pattern();

CREATE FUNCTION mock_guard_set_question_insert() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected integer; actual integer;
BEGIN
    SELECT (configuration->>'total_questions')::integer INTO expected
        FROM mock_tests_mockset WHERE id = NEW.mock_set_id FOR UPDATE;
    SELECT count(*) INTO actual FROM mock_tests_mocksetquestion WHERE mock_set_id = NEW.mock_set_id;
    IF actual >= expected THEN
        RAISE EXCEPTION 'Published Mock sets cannot receive additional questions' USING ERRCODE = '23514';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM mock_tests_mockset s
        JOIN mock_tests_exampatternsection section ON section.pattern_id = s.pattern_id
        JOIN questions_questionrevision revision ON revision.id = NEW.question_revision_id
        WHERE s.id = NEW.mock_set_id AND section.id = NEW.section_id
          AND revision.question_id = NEW.question_id AND revision.published_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'Invalid published set section or approved revision' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER mock_set_question_insert BEFORE INSERT ON mock_tests_mocksetquestion
FOR EACH ROW EXECUTE FUNCTION mock_guard_set_question_insert();

CREATE FUNCTION mock_validate_set_complete() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE expected integer; actual integer; first_position integer; last_position integer;
BEGIN
    expected := (NEW.configuration->>'total_questions')::integer;
    SELECT count(*), min(display_order), max(display_order) INTO actual, first_position, last_position
        FROM mock_tests_mocksetquestion WHERE mock_set_id = NEW.id;
    IF expected IS NULL OR expected <= 0 OR actual <> expected OR first_position <> 1 OR last_position <> expected THEN
        RAISE EXCEPTION 'A published Mock set must have its complete ordered question snapshot' USING ERRCODE = '23514';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER mock_set_complete AFTER INSERT ON mock_tests_mockset
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION mock_validate_set_complete();
"""

REVERSE = """
DROP TRIGGER IF EXISTS mock_set_complete ON mock_tests_mockset;
DROP TRIGGER IF EXISTS mock_set_question_insert ON mock_tests_mocksetquestion;
DROP TRIGGER IF EXISTS mock_frozen_pattern ON mock_tests_exampattern;
DROP TRIGGER IF EXISTS mock_set_question_immutable ON mock_tests_mocksetquestion;
DROP TRIGGER IF EXISTS mock_set_immutable ON mock_tests_mockset;
DROP FUNCTION IF EXISTS mock_validate_set_complete();
DROP FUNCTION IF EXISTS mock_guard_set_question_insert();
DROP FUNCTION IF EXISTS mock_guard_frozen_pattern();
DROP FUNCTION IF EXISTS mock_guard_published_set();
"""


class Migration(migrations.Migration):
    dependencies = [("mock_tests", "0007_mockset_mocksetquestion_exampattern_is_free_demo_and_more")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
