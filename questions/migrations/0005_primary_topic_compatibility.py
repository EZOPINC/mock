from django.db import migrations


BACKFILL = """
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM questions_question q JOIN exams_topic t ON t.id=q.topic_id
           WHERE q.subject_id<>t.subject_id) THEN
  RAISE EXCEPTION 'Resolve question/topic subject mismatches before D3; no tags were backfilled.';
 END IF;
END $$;
INSERT INTO questions_questiontopic(question_id,topic_id,is_primary)
SELECT id,topic_id,TRUE FROM questions_question WHERE topic_id IS NOT NULL
ON CONFLICT(question_id,topic_id) DO UPDATE SET is_primary=TRUE;
"""

GUARDS = """
CREATE FUNCTION questions_guard_topic_tag() RETURNS trigger AS $$
DECLARE owner_id bigint; owner_subject bigint; topic_subject bigint;
BEGIN
 owner_id := CASE WHEN TG_OP='DELETE' THEN OLD.question_id ELSE NEW.question_id END;
 SELECT subject_id INTO owner_subject FROM questions_question WHERE id=owner_id FOR UPDATE;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF;
 IF TG_OP='UPDATE' AND (OLD.question_id<>NEW.question_id OR OLD.topic_id<>NEW.topic_id) THEN
  RAISE EXCEPTION 'Existing topic associations cannot move' USING ERRCODE='23514';
 END IF;
 SELECT subject_id INTO topic_subject FROM exams_topic WHERE id=NEW.topic_id;
 IF owner_subject IS NULL OR topic_subject IS DISTINCT FROM owner_subject THEN
  RAISE EXCEPTION 'Question topic must belong to its subject' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE FUNCTION questions_guard_tagged_subject() RETURNS trigger AS $$
BEGIN
 IF NEW.topic_id IS NOT NULL AND NOT EXISTS(
  SELECT 1 FROM exams_topic WHERE id=NEW.topic_id AND subject_id=NEW.subject_id
 ) THEN
  RAISE EXCEPTION 'Primary topic must belong to the question subject' USING ERRCODE='23514';
 END IF;
 IF EXISTS(SELECT 1 FROM questions_questiontopic qt JOIN exams_topic t ON t.id=qt.topic_id
           WHERE qt.question_id=NEW.id AND t.subject_id<>NEW.subject_id) THEN
  RAISE EXCEPTION 'Remove tags before changing question subject' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE FUNCTION questions_sync_legacy_topic() RETURNS trigger AS $$
BEGIN
 IF TG_OP='UPDATE' THEN
  IF NEW.topic_id IS NOT DISTINCT FROM OLD.topic_id THEN RETURN NEW; END IF;
 END IF;
 IF NEW.topic_id IS NULL THEN
  DELETE FROM questions_questiontopic WHERE question_id=NEW.id;
 ELSE
  UPDATE questions_questiontopic SET is_primary=FALSE WHERE question_id=NEW.id AND is_primary;
  INSERT INTO questions_questiontopic(question_id,topic_id,is_primary) VALUES(NEW.id,NEW.topic_id,TRUE)
  ON CONFLICT(question_id,topic_id) DO UPDATE SET is_primary=TRUE;
 END IF;
 RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE FUNCTION questions_check_primary_topic() RETURNS trigger AS $$
DECLARE owner_id bigint; pointer_id bigint; owner_subject bigint; total bigint; primaries bigint; primary_id bigint;
BEGIN
 IF TG_TABLE_NAME='questions_question' THEN owner_id:=NEW.id;
 ELSE owner_id:=CASE WHEN TG_OP='DELETE' THEN OLD.question_id ELSE NEW.question_id END;
 END IF;
 SELECT topic_id,subject_id INTO pointer_id,owner_subject FROM questions_question WHERE id=owner_id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT count(*),count(*) FILTER(WHERE is_primary),max(topic_id) FILTER(WHERE is_primary)
 INTO total,primaries,primary_id FROM questions_questiontopic WHERE question_id=owner_id;
 IF (total=0 AND pointer_id IS NOT NULL)
 OR (total>0 AND (primaries<>1 OR primary_id IS DISTINCT FROM pointer_id)) THEN
  RAISE EXCEPTION 'Classified questions need exactly one primary tag matching Question.topic' USING ERRCODE='23514';
 END IF;
 IF EXISTS(SELECT 1 FROM questions_questiontopic qt JOIN exams_topic t ON t.id=qt.topic_id
           WHERE qt.question_id=owner_id AND t.subject_id<>owner_subject) THEN
  RAISE EXCEPTION 'Topic subject mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER questions_tag_write_guard BEFORE INSERT OR UPDATE OR DELETE ON questions_questiontopic
FOR EACH ROW EXECUTE FUNCTION questions_guard_topic_tag();
CREATE TRIGGER questions_subject_tag_guard BEFORE INSERT OR UPDATE OF subject_id,topic_id ON questions_question
FOR EACH ROW EXECUTE FUNCTION questions_guard_tagged_subject();
CREATE TRIGGER questions_legacy_topic_sync AFTER INSERT OR UPDATE OF topic_id ON questions_question
FOR EACH ROW EXECUTE FUNCTION questions_sync_legacy_topic();
CREATE CONSTRAINT TRIGGER questions_primary_tag_consistency AFTER INSERT OR UPDATE ON questions_question
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION questions_check_primary_topic();
CREATE CONSTRAINT TRIGGER questions_tag_pointer_consistency AFTER INSERT OR UPDATE OR DELETE ON questions_questiontopic
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION questions_check_primary_topic();
"""

REMOVE = """
DROP TRIGGER questions_tag_pointer_consistency ON questions_questiontopic;
DROP TRIGGER questions_primary_tag_consistency ON questions_question;
DROP TRIGGER questions_legacy_topic_sync ON questions_question;
DROP TRIGGER questions_subject_tag_guard ON questions_question;
DROP TRIGGER questions_tag_write_guard ON questions_questiontopic;
DROP FUNCTION questions_check_primary_topic();
DROP FUNCTION questions_sync_legacy_topic();
DROP FUNCTION questions_guard_tagged_subject();
DROP FUNCTION questions_guard_topic_tag();
"""

SAFE_ROLLBACK = """
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM questions_questiontopic WHERE NOT is_primary) THEN
  RAISE EXCEPTION 'D3 rollback blocked: secondary topic tags would be lost. Export and resolve them explicitly first.';
 END IF;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("questions", "0004_questiontopic_question_topics_and_more"),
        ("exams", "0004_flexible_academic_taxonomy"),
    ]
    operations = [
        migrations.RunSQL(BACKFILL, migrations.RunSQL.noop),
        migrations.RunSQL(GUARDS, REMOVE),
        migrations.RunSQL(migrations.RunSQL.noop, SAFE_ROLLBACK),
    ]
