from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction
from django.test import Client, TransactionTestCase
from django.urls import reverse
from accounts.dashboard import dashboard_context
from exams.models import Chapter, Module, Part, Topic
from mock_tests.test_execution import ExecutionFixture
from practice.models import PracticeQuestion, PracticeSession
from practice.services import complete_session, submit_answer
from practice.tests import PracticeFixture
from questions.models import Question, QuestionExam
from questions.services import add_translation, create_revision, mark_reviewed, publish_question
from questions.tagging import set_question_topics
from .models import RevisionSession, SavedQuestion
from .sessions import start_revision


class RevisionSessionTests(PracticeFixture):
    def setUp(self):
        self.client.force_login(self.user)

    def saved(self, **kwargs):
        return SavedQuestion.objects.create(user=self.user, question=self.question(**kwargs))

    def start(self, **kwargs):
        return start_revision(self.user, {"token": uuid4(), **kwargs})

    def url(self, session):
        return reverse("revision:session", args=[session.pk])

    def answer_url(self, session, row):
        return reverse("revision:answer", args=[session.pk, row.pk])

    def test_all_saved_spans_exams_subjects_and_deduplicates(self):
        first = self.saved()
        second = self.saved(subject=self.other_subject, exam=self.other_exam)
        QuestionExam.objects.create(question=first.question, exam=self.other_exam)
        unsaved = self.question()
        session = self.start()
        self.assertEqual(set(session.questions.values_list("question_id", flat=True)), {first.question_id, second.question_id})
        self.assertEqual(session.kind, "revision")
        self.assertIsNone(session.exam_id)
        self.assertIsNone(session.subject_id)
        self.assertEqual(list(session.questions.values_list("display_order", flat=True)), [1, 2])
        self.assertEqual(RevisionSession.objects.count(), 1)

    def test_filtered_secondary_hierarchy_mastery_and_question_limit(self):
        part = Part.objects.create(subject=self.subject, name="Part", slug="part")
        module = Module.objects.create(part=part, name="Module", slug="module")
        chapter = Chapter.objects.create(module=module, name="Chapter", slug="chapter")
        topic = Topic.objects.create(chapter=chapter, subject=self.subject, name="Secondary", slug="secondary")
        first, second, other = self.saved(), self.saved(), self.saved()
        for saved in (first, second):
            set_question_topics(saved.question, [self.topic.pk, topic.pk], primary_topic_id=self.topic.pk)
            SavedQuestion.objects.filter(pk=saved.pk).update(is_mastered=True)
        session = self.start(exam=str(self.exam.pk), subject=str(self.subject.pk), part=str(part.pk), module=str(module.pk), chapter=str(chapter.pk), topic=str(topic.pk), mastery="mastered", question_limit="1")
        self.assertEqual(session.questions.count(), 1)
        self.assertIn(session.questions.get().question_id, {first.question_id, second.question_id})
        self.assertEqual(session.configuration["revision_request"]["module"], str(module.pk))
        self.assertEqual(self.start(module=str(module.pk), question_limit="100").questions.count(), 2)

    def test_eligibility_excludes_drafts_inactive_unsupported_and_other_users(self):
        good = self.saved()
        self.saved(published=False)
        self.saved(exam=self.other_exam)
        self.other_exam.is_active = False
        self.other_exam.save()
        unsupported = self.saved()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE questions_questiontranslation SET language='xx' WHERE revision_id=%s", [unsupported.question.published_revision_id])
        SavedQuestion.objects.create(user=self.other_user, question=self.question())
        self.assertEqual(self.start().questions.get().question_id, good.question_id)

    def test_empty_or_invalid_creation_has_no_partial_session(self):
        for values in ({}, {"question_limit": "-1"}, {"question_limit": "0"}, {"question_limit": "10001"}, {"question_limit": "bad"}, {"token": "bad"}, {"mastery": "bad"}):
            with self.assertRaises(ValidationError):
                self.start(**values)
        self.assertFalse(RevisionSession.objects.exists())
        self.assertFalse(PracticeQuestion.objects.exists())
        self.saved()
        with self.assertRaises(ValidationError):
            self.start(subject=str(self.other_subject.pk))

    def test_start_token_retry_after_bookmark_change_and_token_scope(self):
        saved = self.saved()
        token = uuid4()
        session = self.start(token=token, subject=str(self.subject.pk))
        SavedQuestion.objects.filter(pk=saved.pk).delete()
        self.assertEqual(self.start(token=token, subject=str(self.subject.pk)).pk, session.pk)
        self.assertEqual(session.questions.count(), 1)
        with self.assertRaises(ValidationError):
            self.start(token=token, question_limit="1")
        response = self.client.post(reverse("revision:start"), {"token": token, "subject": self.subject.pk})
        self.assertRedirects(response, self.url(session))
        self.assertEqual(RevisionSession.objects.count(), 1)

    def test_answer_feedback_lock_review_count_and_mastery_are_independent(self):
        saved = self.saved()
        session = self.start()
        row = session.questions.get()
        self.assertNotContains(self.client.get(self.url(session)), "VERIFIED SOLUTION")
        self.assertNotContains(self.client.get(self.url(session)), "Correct answer:")
        response = self.client.post(self.answer_url(session, row), {"answer": "B"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "VERIFIED SOLUTION")
        self.assertContains(response, "Answer locked")
        self.assertNotContains(response, '<html')
        saved.refresh_from_db()
        row.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(saved.review_count, 1)
        self.assertIsNotNone(saved.reviewed_at)
        self.assertFalse(saved.is_mastered)
        self.assertFalse(row.is_correct)
        self.assertEqual(session.status, "completed")
        original_time = saved.reviewed_at
        submit_answer(self.user, session.pk, row.pk, "B")
        self.client.get(self.url(session))
        self.client.get(reverse("revision:results", args=[session.pk]))
        self.client.post(self.answer_url(session, row), {"answer": "B"})
        with self.assertRaises(ValidationError):
            submit_answer(self.user, session.pk, row.pk, "A")
        saved.refresh_from_db()
        self.assertEqual(saved.review_count, 1)
        self.assertEqual(saved.reviewed_at, original_time)
        url = reverse("revision:mastery", args=[session.pk, row.pk])
        self.client.post(url, {"action": "mastered"})
        saved.refresh_from_db()
        self.assertTrue(saved.is_mastered)
        self.client.post(url, {"action": "needs_revision"})
        saved.refresh_from_db()
        self.assertFalse(saved.is_mastered)

    def test_review_counter_failure_rolls_back_answer_and_completion(self):
        saved = self.saved()
        session = self.start()
        row = session.questions.get()
        with patch("revision.sessions.record_review", side_effect=ValidationError("Counter failure")):
            with self.assertRaises(ValidationError):
                submit_answer(self.user, session.pk, row.pk, "A")
        row.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(row.selected_answer, "")
        self.assertEqual(session.status, "in_progress")

    def test_bookmark_taxonomy_and_publication_changes_preserve_frozen_session(self):
        saved = self.saved()
        session = self.start()
        row = session.questions.get()
        revision_id = row.question_revision_id
        frozen = dict(row.classification)
        SavedQuestion.objects.filter(pk=saved.pk).delete()
        set_question_topics(saved.question, [], primary_topic_id=None)
        create_revision(saved.question, language="en", question_text="Later question", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="D")
        publish_question(mark_reviewed(saved.question))
        with connection.cursor() as cursor:
            cursor.execute("UPDATE questions_question SET publication_status='draft', published_revision_id=NULL WHERE id=%s", [saved.question_id])
        self.assertContains(self.client.get(self.url(session)), row.question_revision.question_text)
        submit_answer(self.user, session.pk, row.pk, "A")
        row.refresh_from_db()
        self.assertEqual(row.question_revision_id, revision_id)
        self.assertEqual(row.classification, frozen)
        self.assertTrue(row.is_correct)
        self.assertFalse(SavedQuestion.objects.exists())
        self.assertContains(self.client.get(reverse("revision:results", args=[session.pk])), "100.00%")

    def test_bilingual_feedback_and_resume_answer_persistence(self):
        saved = self.saved()
        add_translation(saved.question, language="bn", question_text="\u09ac\u09be\u0982\u09b2\u09be", option_a="A", option_b="B", option_c="C", option_d="D", explanation="Bengali solution")
        publish_question(mark_reviewed(saved.question))
        self.saved()
        session = self.start()
        row = session.questions.get(question_id=saved.question_id)
        self.assertContains(self.client.get(self.url(session) + f"?question={row.display_order}"), "\u09ac\u09be\u0982\u09b2\u09be")
        self.client.post(self.answer_url(session, row), {"answer": "A"})
        response = self.client.get(self.url(session) + f"?question={row.display_order}")
        self.assertContains(response, "Bengali solution")
        self.assertContains(response, "Answer locked")
        resumed = self.client.get(self.url(session))
        self.assertNotEqual(resumed.context["row"].pk, row.pk)
        self.assertEqual(resumed.context["progress"]["answered"], 1)

    def test_completion_results_unanswered_incorrect_filter_and_history(self):
        for _ in range(3):
            self.saved()
        session = self.start()
        rows = list(session.questions.all())
        submit_answer(self.user, session.pk, rows[0].pk, "A")
        submit_answer(self.user, session.pk, rows[1].pk, "B")
        finish_url = reverse("revision:finish", args=[session.pk])
        self.assertEqual(self.client.get(finish_url).status_code, 200)
        self.assertEqual(self.client.post(finish_url).status_code, 400)
        self.assertRedirects(self.client.post(finish_url, {"confirm": "yes"}), reverse("revision:results", args=[session.pk]))
        complete_session(self.user, session.pk)
        with self.assertRaises(ValidationError):
            submit_answer(self.user, session.pk, rows[2].pk, "A")
        response = self.client.get(reverse("revision:results", args=[session.pk]))
        self.assertEqual(response.context["progress"], {"total": 3, "answered": 2, "correct": 1, "incorrect": 1, "remaining": 1, "accuracy": 50, "percent": response.context["progress"]["percent"]})
        wrong = self.client.get(reverse("revision:results", args=[session.pk]), {"incorrect": "1"})
        self.assertEqual([r.pk for r in wrong.context["rows"]], [rows[1].pk])
        self.assertContains(self.client.get(reverse("revision:history")), "Revision session")
        self.assertContains(self.client.get(reverse("revision:dashboard")), "Revisit")

    def test_auth_csrf_cross_user_and_cross_session_row_rejection(self):
        self.saved()
        session = self.start()
        other_session = self.start()
        row = session.questions.get()
        urls = [self.url(session), reverse("revision:results", args=[session.pk]), reverse("revision:finish", args=[session.pk])]
        self.client.force_login(self.other_user)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(self.answer_url(session, row), {"answer": "A"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("revision:mastery", args=[session.pk, row.pk]), {"action": "mastered"}).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.answer_url(other_session, row), {"answer": "A"}).status_code, 404)
        self.assertEqual(self.client.get(self.answer_url(session, row)).status_code, 405)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        for url in (reverse("revision:start"), self.answer_url(session, row), reverse("revision:mastery", args=[session.pk, row.pk]), reverse("revision:finish", args=[session.pk])):
            self.assertEqual(strict.post(url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(self.url(session)).status_code, 302)
        self.assertEqual(self.client.post(self.answer_url(session, row), {"answer": "A"}).status_code, 302)

    def test_revision_is_separate_from_normal_practice_and_immutable(self):
        self.saved()
        normal = self.session()
        revision = self.start()
        self.assertEqual(dashboard_context(self.user)["practice_stats"]["total"], 1)
        self.assertEqual([s.pk for s in self.client.get(reverse("practice:index")).context["open_sessions"]], [normal.pk])
        self.assertEqual(self.client.get(reverse("practice:session", args=[revision.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("revision:session", args=[normal.pk])).status_code, 404)
        with self.assertRaises(ValidationError):
            revision.configuration = {"changed": True}
            revision.save()
        with self.assertRaises(ValidationError):
            revision.questions.all().delete()
        with self.assertRaises(ValidationError):
            self.start(token=normal.start_token)

    def test_creation_rollback_and_start_ui_preserves_filters(self):
        self.saved()
        query = {"subject": str(self.subject.pk), "mastery": "needs_revision"}
        response = self.client.get(reverse("revision:dashboard"), query)
        self.assertContains(response, "Start Revision")
        self.assertContains(response, "subject=" + str(self.subject.pk))
        setup = self.client.get(reverse("revision:start"), query)
        self.assertFalse(RevisionSession.objects.exists())
        self.assertEqual(setup.context["eligible_count"], 1)
        token = setup.context["form"]["token"].value()
        with patch("practice.models.PracticeQuestion.save", side_effect=ValidationError("Row failure")):
            with self.assertRaises(ValidationError):
                self.start()
        self.assertFalse(RevisionSession.objects.exists())
        response = self.client.post(reverse("revision:start"), {"token": token, **query})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(RevisionSession.objects.count(), 1)


class RevisionMockEligibilityTests(ExecutionFixture):
    def test_open_mock_question_is_excluded_without_changing_attempt(self):
        attempt = self.ready_attempt()
        row = attempt.questions.get()
        SavedQuestion.objects.create(user=self.user, question=row.question)
        before = type(attempt).objects.filter(pk=attempt.pk).values().get()
        with self.assertRaises(ValidationError):
            start_revision(self.user, {"token": uuid4()})
        self.assertEqual(before, type(attempt).objects.filter(pk=attempt.pk).values().get())
        self.assertFalse(RevisionSession.objects.exists())


class ConcurrentRevisionTests(TransactionTestCase):
    question = PracticeFixture.question

    def setUp(self):
        PracticeFixture.setUpTestData.__func__(type(self))
        question = self.question()
        SavedQuestion.objects.create(user=self.user, question=question)

    def test_duplicate_start_and_answer_requests_are_serialized(self):
        token = uuid4()
        barrier = Barrier(2)
        def start():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return start_revision(self.user, {"token": token}).pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(lambda _: start(), range(2)))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(RevisionSession.objects.count(), 1)
        session = RevisionSession.objects.get()
        row = session.questions.get()
        barrier = Barrier(2)
        def answer():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return submit_answer(self.user, session.pk, row.pk, "A").pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(lambda _: answer(), range(2))), [row.pk, row.pk])
        self.assertEqual(SavedQuestion.objects.get().review_count, 1)


from django.db.migrations.executor import MigrationExecutor


class RevisionEngineMigrationTests(TransactionTestCase):
    def test_legacy_practice_session_survives_scope_migration(self):
        PracticeFixture.setUpTestData.__func__(type(self))
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        old = [("practice", "0001_initial"), ("revision", "0002_savedquestion_is_mastered_and_more")]
        executor.migrate(old)
        try:
            apps = executor.loader.project_state(old).apps
            historical = apps.get_model("practice", "PracticeSession").objects.create(
                user_id=self.user.pk, exam_id=self.exam.pk, subject_id=self.subject.pk,
                start_token=uuid4(), configuration={"exam_name": "Original exam", "requested_count": "available"})
            original = historical.started_at
            MigrationExecutor(connection).migrate(latest)
            restored = PracticeSession.objects.get(pk=historical.pk)
            self.assertEqual(restored.kind, "practice")
            self.assertEqual(restored.exam_id, self.exam.pk)
            self.assertEqual(restored.subject_id, self.subject.pk)
            self.assertEqual(restored.started_at, original)
            self.assertEqual(restored.configuration["exam_name"], "Original exam")
            self.assertEqual(restored.status, "in_progress")
        finally:
            MigrationExecutor(connection).migrate(latest)
