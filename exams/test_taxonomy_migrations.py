from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


OLD = [("exams", "0003_taxonomy_integrity")]
NEW = [("exams", "0004_flexible_academic_taxonomy")]


class FlexibleTaxonomyMigrationTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        self.latest = executor.loader.graph.leaf_nodes()
        executor.migrate(OLD)
        # Include unchanged apps in the historical state to exercise real references.
        self.old_apps = executor.loader.project_state([node for node in self.latest if node[0] != "exams"] + OLD).apps

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.latest)
        super().tearDown()

    def seed(self):
        apps = self.old_apps
        subject = apps.get_model("exams", "Subject").objects.create(name="History", code="original-code", slug="history")
        part = apps.get_model("exams", "Part").objects.create(subject_id=subject.pk, name="India", slug="india")
        module = apps.get_model("exams", "Module").objects.create(part_id=part.pk, name="Ancient", slug="ancient")
        chapter = apps.get_model("exams", "Chapter").objects.create(module_id=module.pk, name="Stone age", slug="stone-age")
        topic = apps.get_model("exams", "Topic").objects.create(subject_id=subject.pk, chapter_id=chapter.pk, name="Paleolithic", slug="paleolithic")
        flat = apps.get_model("exams", "Topic").objects.create(subject_id=subject.pk, name="Unclassified", slug="unclassified")
        question = apps.get_model("questions", "Question").objects.create(subject_id=subject.pk, topic_id=topic.pk)
        revision = apps.get_model("questions", "QuestionRevision").objects.create(question_id=question.pk, revision_number=1,
            language="en", question_text="Original text", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="A", difficulty_level="Medium")
        apps.get_model("questions", "QuestionTranslation").objects.create(question_id=question.pk, revision_id=revision.pk,
            language="en", question_text="Original text", option_a="A", option_b="B", option_c="C", option_d="D")
        no_topic = apps.get_model("questions", "Question").objects.create(subject_id=subject.pk)
        return subject, part, module, chapter, topic, flat, question, revision, no_topic

    def migrate_new(self):
        executor = MigrationExecutor(connection)
        executor.migrate(NEW)
        return executor.loader.project_state([node for node in self.latest if node[0] != "exams"] + NEW).apps

    def test_forward_backfill_preserves_ids_paths_names_and_revisions(self):
        subject, part, module, chapter, topic, flat, question, revision, no_topic = self.seed()
        apps = self.migrate_new()
        for label, record, prefix in (("Part", part, "PART"), ("Module", module, "MODULE"),
                                      ("Chapter", chapter, "CHAPTER"), ("Topic", topic, "TOPIC")):
            current = apps.get_model("exams", label).objects.get(pk=record.pk)
            self.assertEqual(current.name, record.name)
            self.assertEqual(current.code, f"{prefix}-{record.pk}")
            self.assertEqual(current.subject_id, subject.pk)
        self.assertEqual(apps.get_model("exams", "Subject").objects.get(pk=subject.pk).code, "original-code")
        self.assertIsNone(apps.get_model("exams", "Topic").objects.get(pk=flat.pk).chapter_id)
        self.assertIsNone(apps.get_model("questions", "Question").objects.get(pk=no_topic.pk).topic_id)
        self.assertEqual(apps.get_model("questions", "Question").objects.get(pk=question.pk).topic_id, topic.pk)
        frozen = apps.get_model("questions", "QuestionRevision").objects.get(pk=revision.pk)
        self.assertEqual((frozen.question_text, frozen.difficulty_level), ("Original text", "Medium"))
        self.assertEqual(apps.get_model("questions", "QuestionTranslation").objects.filter(revision_id=revision.pk).count(), 1)
        # Safe legacy-shaped rollback keeps old records and reinstalls old triggers.
        MigrationExecutor(connection).migrate(OLD)
        self.assertEqual(self.old_apps.get_model("exams", "Topic").objects.get(pk=topic.pk).chapter_id, chapter.pk)
        apps = self.migrate_new()
        self.assertEqual(apps.get_model("exams", "Topic").objects.get(pk=topic.pk).code, f"TOPIC-{topic.pk}")

    def test_rollback_refuses_to_drop_optional_paths(self):
        subject, *_ = self.seed()
        apps = self.migrate_new()
        model = apps.get_model("exams", "Module")
        model.objects.create(subject_id=subject.pk, name="Direct module", slug="direct", code="CUSTOM")
        with self.assertRaisesMessage(DatabaseError, "D2 rollback blocked"):
            MigrationExecutor(connection).migrate(OLD)
        # Failed rollback is atomic, retaining the new record and complete schema.
        self.assertEqual(model.objects.get(code="CUSTOM").subject_id, subject.pk)
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgname IN ('exams_part_parent_guard','exams_module_parent_guard','exams_chapter_parent_guard','exams_topic_hierarchy_guard')")
            self.assertEqual(cursor.fetchone()[0], 4)

    def test_rollback_preserves_new_codes_by_refusing_unsafe_drop(self):
        self.seed()
        apps = self.migrate_new()
        subject = apps.get_model("exams", "Subject").objects.get(code="original-code")
        part_model = apps.get_model("exams", "Part")
        part_model.objects.create(subject_id=subject.pk, name="New part", slug="new", code="CUSTOM-NEW")
        with self.assertRaisesMessage(DatabaseError, "D2 rollback blocked"):
            MigrationExecutor(connection).migrate(OLD)
        self.assertEqual(part_model.objects.get(code="CUSTOM-NEW").name, "New part")
