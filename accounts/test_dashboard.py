from uuid import uuid4

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from practice import tests as practice_fixtures
from practice.services import start_session, submit_answer
from mock_tests.models import ExamPattern, ExamPatternSection
from mock_tests.services import activate_pattern, start_attempt
from mock_tests.execution import submit_attempt
from .dashboard import dashboard_context


class StudentDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        practice_fixtures.PracticeFixture.setUpTestData.__func__(cls)
        cls.user.email = "student@dashboard.test"
        cls.user.save(update_fields=["email"])
        cls.other_user.email = "private-other@dashboard.test"
        cls.other_user.save(update_fields=["email"])

    question = practice_fixtures.PracticeFixture.question

    def practice(self, user=None):
        return start_session(user or self.user, exam=self.exam, subject=self.subject, token=uuid4())

    def pattern(self, name="Student mock"):
        pattern = ExamPattern.objects.create(exam=self.exam, name=name, duration_minutes=60, total_questions=1, total_marks=1)
        ExamPatternSection.objects.create(pattern=pattern, name="Section", display_order=1, question_count=1)
        return activate_pattern(pattern)

    def test_guest_redirect_and_empty_dashboard(self):
        url = reverse("accounts:learning_space")
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertContains(response, "Your first mock test starts here.")
        self.assertContains(response, "Submit a practice answer to see your accuracy.")
        self.assertNotContains(response, "Account details")
        self.assertEqual(response.context["mock_stats"]["total"], 0)
        self.assertIsNone(response.context["practice_accuracy"])
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_activity_counts_resume_and_result_links(self):
        self.question()
        pattern = self.pattern()
        final = submit_attempt(self.user, start_attempt(self.user, pattern).pk)
        open_attempt = start_attempt(self.user, pattern)
        completed = self.practice()
        submit_answer(self.user, completed.pk, completed.questions.get().pk, "A")
        open_practice = self.practice()
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:learning_space"))
        self.assertEqual(response.context["mock_stats"], {"total": 2, "finished": 1, "open": 1})
        self.assertEqual(response.context["practice_stats"], {"total": 2, "completed": 1, "open": 1})
        self.assertEqual(response.context["practice_accuracy"], 100)
        for name, pk in (("mock_tests:results", final.pk), ("mock_tests:attempt_detail", open_attempt.pk),
            ("practice:summary", completed.pk), ("practice:session", open_practice.pk)):
            self.assertContains(response, reverse(name, args=[pk]))
        self.assertNotContains(response, "Correct answer")
        self.assertNotContains(response, "VERIFIED SOLUTION")
        self.assertNotContains(response, self.user.password)

    def test_activity_is_scoped_to_authenticated_user_not_query_parameter(self):
        self.question()
        pattern = self.pattern()
        owned_attempt = start_attempt(self.user, pattern)
        private_attempt = start_attempt(self.other_user, pattern)
        owned_session = self.practice()
        private_session = self.practice(self.other_user)
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:learning_space"), {"user": self.other_user.pk})
        self.assertEqual([row.pk for row in response.context["recent_mock_attempts"]], [owned_attempt.pk])
        self.assertEqual([row.pk for row in response.context["recent_practice_sessions"]], [owned_session.pk])
        self.assertNotContains(response, reverse("mock_tests:attempt_detail", args=[private_attempt.pk]))
        self.assertNotContains(response, reverse("practice:session", args=[private_session.pk]))
        self.assertNotContains(response, self.other_user.email)

    def test_recent_activity_is_bounded_and_does_not_write_learning_records(self):
        self.question()
        for _ in range(6):
            self.practice()
        with CaptureQueriesContext(connection) as captured:
            data = dashboard_context(self.user)
        self.assertEqual(data["practice_stats"]["total"], 6)
        self.assertEqual(len(data["recent_practice_sessions"]), 5)
        self.assertTrue(all(query["sql"].lstrip().upper().startswith("SELECT") for query in captured.captured_queries))
        self.assertTrue(all(row.status == "in_progress" for row in data["recent_practice_sessions"]))

    def test_bilingual_master_counts_once_and_incorrect_answers_affect_accuracy(self):
        from questions.services import add_translation, mark_reviewed, publish_question
        question = self.question()
        add_translation(question, language="bn", question_text="Bengali version", option_a="A", option_b="B", option_c="C", option_d="D")
        publish_question(mark_reviewed(question))
        session = self.practice()
        submit_answer(self.user, session.pk, session.questions.get().pk, "B")
        data = dashboard_context(self.user)
        self.assertEqual(data["practice_answer_stats"], {"answered": 1, "correct": 0})
        self.assertEqual(data["practice_accuracy"], 0)
        self.assertEqual(data["recent_practice_sessions"][0].question_count, 1)
        self.assertEqual(data["recent_practice_sessions"][0].answered_count, 1)

    def test_invalid_authentication_form_has_accessible_errors(self):
        response = self.client.post(reverse("accounts:login"), {"username": "unknown", "password": "wrong"})
        self.assertContains(response, 'role="alert"')
        self.assertContains(response, 'class="form-errors"')
        self.assertContains(response, 'name="next"')
        self.assertNotIn("_auth_user_id", self.client.session)
