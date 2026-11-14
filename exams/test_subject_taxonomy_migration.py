from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class TaxonomyMetadataMigrationTests(TransactionTestCase):
    def test_existing_taxonomy_ids_and_legacy_parents_survive(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old_target = [("exams", "0004_flexible_academic_taxonomy")]
        executor.migrate(old_target)
        try:
            apps = executor.loader.project_state(old_target).apps
            subject = apps.get_model("exams", "Subject").objects.create(
                code="MIGRATION", name="Migration subject", slug="migration-subject")
            topic = apps.get_model("exams", "Topic").objects.create(
                subject_id=subject.pk, code="MIGRATION-T", name="Legacy topic", slug="legacy-topic")
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            apps = executor.loader.project_state(latest).apps
            updated = apps.get_model("exams", "Topic").objects.get(pk=topic.pk)
            self.assertEqual(updated.subject_id, subject.pk)
            self.assertEqual(updated.code, "MIGRATION-T")
            self.assertIsNone(updated.chapter_id)
            self.assertEqual(updated.notes, "")
            self.assertEqual(apps.get_model("exams", "Subject").objects.get(pk=subject.pk).display_order, 0)
        finally:
            MigrationExecutor(connection).migrate(latest)
