from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class TranslationMigrationTests(TransactionTestCase):
    def test_existing_published_question_and_revision_are_preserved(self):
        executor = MigrationExecutor(connection)
        restore = executor.loader.graph.leaf_nodes()
        old = ("questions", "0001_initial")
        latest = ("questions", "0003_backfill_translations")
        executor.migrate([old])
        try:
            paper_node = executor.loader.graph.leaf_nodes("previous_year")[0]
            old_apps = executor.loader.project_state([old, paper_node]).apps
            Subject = old_apps.get_model("exams", "Subject")
            Question = old_apps.get_model("questions", "Question")
            Revision = old_apps.get_model("questions", "QuestionRevision")
            subject = Subject.objects.create(name="Migration subject", code="MIGRATE", slug="migrate")
            question = Question.objects.create(subject=subject)
            from django.utils import timezone
            revision = Revision.objects.create(question=question, revision_number=1, language="bn", question_text="পুরনো প্রশ্ন", option_a="এক", option_b="দুই", option_c="তিন", option_d="চার", correct_answer="A", published_at=timezone.now())
            Question.objects.filter(pk=question.pk).update(current_revision=revision, published_revision=revision, review_status="reviewed", publication_status="published")
            authority = old_apps.get_model("exams", "ExamAuthority").objects.create(name="Legacy authority", code="LEGACY", slug="legacy")
            exam = old_apps.get_model("exams", "Exam").objects.create(authority=authority, name="Legacy exam", code="LEGACY", slug="legacy")
            old_apps.get_model("questions", "QuestionExam").objects.create(question=question, exam=exam)
            paper = old_apps.get_model("previous_year", "PreviousYearPaper").objects.create(exam=exam, year=2023, paper_name="Legacy paper", is_published=True)
            association = old_apps.get_model("previous_year", "PaperQuestion").objects.create(paper=paper, question=question, question_revision=revision, question_number="1", display_order=1)
            executor = MigrationExecutor(connection)
            executor.migrate([latest])
            current = executor.loader.project_state([latest]).apps
            migrated = current.get_model("questions", "Question").objects.get(pk=question.pk)
            translation = current.get_model("questions", "QuestionTranslation").objects.get(revision_id=revision.pk)
            self.assertEqual(migrated.published_revision_id, revision.pk)
            self.assertEqual(migrated.current_revision_id, revision.pk)
            self.assertEqual(migrated.correct_answer, "A")
            self.assertEqual(migrated.publication_status, "published")
            self.assertEqual(translation.question_id, question.pk)
            self.assertEqual(translation.question_text, "পুরনো প্রশ্ন")
            from previous_year.models import PaperQuestion
            self.assertEqual(PaperQuestion.objects.get(pk=association.pk).question_revision_id, revision.pk)
        finally:
            MigrationExecutor(connection).migrate(restore)
