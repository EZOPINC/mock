from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class AttemptDeadlineMigrationTests(TransactionTestCase):
    def test_existing_attempt_keeps_identity_and_snapshot_duration(self):
        executor = MigrationExecutor(connection)
        restore = executor.loader.graph.leaf_nodes()
        old = [("mock_tests", "0002_mockattempt_attemptquestion_and_more")]
        latest = [("mock_tests", "0005_mockattempt_mock_attempt_deadline_valid_and_more")]
        executor.migrate(old)
        try:
            apps = executor.loader.project_state(old).apps
            User = apps.get_model("accounts", "User")
            Authority = apps.get_model("exams", "ExamAuthority")
            Exam = apps.get_model("exams", "Exam")
            Pattern = apps.get_model("mock_tests", "ExamPattern")
            Attempt = apps.get_model("mock_tests", "MockAttempt")
            authority = Authority.objects.create(name="Authority", code="A", slug="authority")
            exam = Exam.objects.create(authority=authority, name="Exam", code="E", slug="exam")
            pattern = Pattern.objects.create(exam=exam, name="Pattern", duration_minutes=90, total_questions=1, total_marks=1)
            user = User.objects.create(username="legacy")
            started = timezone.now() - timedelta(minutes=10)
            attempt = Attempt.objects.create(user=user, pattern=pattern, status="in_progress", started_at=started,
                configuration={"name": "Frozen", "duration_minutes": 30, "total_questions": 1, "sections": []})
            executor = MigrationExecutor(connection)
            executor.migrate(latest)
            new_apps = executor.loader.project_state(latest).apps
            restored = new_apps.get_model("mock_tests", "MockAttempt").objects.get(pk=attempt.pk)
            self.assertEqual(restored.expires_at, started + timedelta(minutes=30))
            self.assertEqual(restored.configuration["name"], "Frozen")
            self.assertEqual(restored.status, "in_progress")
            self.assertEqual(restored.save_version, 0)
        finally:
            MigrationExecutor(connection).migrate(restore)
