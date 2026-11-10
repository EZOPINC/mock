from importlib import import_module

from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


OLD = [("questions", "0003_backfill_translations")]
NEW = [("questions", "0005_primary_topic_compatibility")]


class QuestionTopicMigrationTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        self.restore = executor.loader.graph.leaf_nodes()
        executor.migrate(OLD)
        self.apps = executor.loader.project_state([node for node in self.restore if node[0] != "questions"] + OLD).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.restore)
        super().tearDown()

    def seed(self):
        apps = self.apps
        subject = apps.get_model("exams", "Subject").objects.create(name="History", code="H", slug="history")
        topic = apps.get_model("exams", "Topic").objects.create(subject=subject, name="Ancient", slug="ancient")
        question = apps.get_model("questions", "Question").objects.create(subject=subject, topic=topic)
        empty = apps.get_model("questions", "Question").objects.create(subject=subject)
        revision = apps.get_model("questions", "QuestionRevision").objects.create(question=question, revision_number=1,
            language="en", question_text="Frozen original", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="A", difficulty_level="Medium")
        apps.get_model("questions", "QuestionTranslation").objects.create(question=question, revision=revision,
            language="en", question_text="Frozen original", option_a="A", option_b="B", option_c="C", option_d="D")
        authority = apps.get_model("exams", "ExamAuthority").objects.create(name="Authority", code="A", slug="authority")
        exam = apps.get_model("exams", "Exam").objects.create(authority=authority, name="Exam", code="E", slug="exam")
        apps.get_model("questions", "QuestionExam").objects.create(question=question, exam=exam)
        paper = apps.get_model("previous_year", "PreviousYearPaper").objects.create(exam=exam, year=2020, paper_name="Frozen paper")
        association = apps.get_model("previous_year", "PaperQuestion").objects.create(paper=paper, question=question,
            question_revision=revision, question_number="10(a)", display_order=1)
        return subject, topic, question, empty, revision, association

    def migrate_new(self):
        executor = MigrationExecutor(connection)
        executor.migrate(NEW)
        return executor.loader.project_state([node for node in self.restore if node[0] != "questions"] + NEW).apps

    def test_backfill_idempotency_and_legacy_safe_rollback(self):
        subject, topic, question, empty, revision, association = self.seed()
        apps = self.migrate_new()
        tags = apps.get_model("questions", "QuestionTopic")
        tag = tags.objects.get(question_id=question.pk)
        self.assertEqual((tag.topic_id, tag.is_primary), (topic.pk, True))
        self.assertFalse(tags.objects.filter(question_id=empty.pk).exists())
        with connection.cursor() as cursor:
            cursor.execute(import_module("questions.migrations.0005_primary_topic_compatibility").BACKFILL)
        self.assertEqual(tags.objects.get(question_id=question.pk).pk, tag.pk)
        self.assertEqual(tags.objects.count(), 1)
        stored = apps.get_model("questions", "QuestionRevision").objects.get(pk=revision.pk)
        self.assertEqual((stored.question_text, stored.difficulty_level), ("Frozen original", "Medium"))
        self.assertEqual(apps.get_model("previous_year", "PaperQuestion").objects.get(pk=association.pk).question_revision_id, revision.pk)
        self.assertEqual(apps.get_model("questions", "QuestionExam").objects.filter(question_id=question.pk).count(), 1)
        MigrationExecutor(connection).migrate(OLD)
        self.assertEqual(self.apps.get_model("questions", "Question").objects.get(pk=question.pk).topic_id, topic.pk)
        apps = self.migrate_new()
        self.assertEqual(apps.get_model("questions", "QuestionTopic").objects.get(question_id=question.pk).topic_id, topic.pk)

    def test_rollback_refuses_secondary_tag_loss(self):
        subject, topic, question, *_ = self.seed()
        apps = self.migrate_new()
        extra = apps.get_model("exams", "Topic").objects.create(subject_id=subject.pk, name="Modern", slug="modern")
        tags = apps.get_model("questions", "QuestionTopic")
        tags.objects.create(question_id=question.pk, topic_id=extra.pk, is_primary=False)
        with self.assertRaisesMessage(DatabaseError, "D3 rollback blocked"):
            MigrationExecutor(connection).migrate(OLD)
        self.assertEqual(tags.objects.filter(question_id=question.pk).count(), 2)
