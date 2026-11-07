import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from uuid import uuid4
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from questions.services import create_revision, mark_reviewed, publish_question
from . import test_attempts, test_patterns
from .execution import refresh_attempt, save_response, submit_attempt
from .models import AttemptQuestion, ExamPattern, ExamPatternSection, MockAttempt
from .services import activate_pattern, start_attempt


class ExecutionFixture(test_attempts.AttemptFixture):
    def ready_attempt(self, count=1):
        self.pattern.total_questions = count
        self.pattern.total_marks = count
        self.pattern.save()
        self.section.question_count = count
        self.section.save()
        for _ in range(count):
            self.question()
        activate_pattern(self.pattern)
        return start_attempt(self.user, self.pattern)

    def payload(self, attempt, row=None, **overrides):
        row = row or attempt.questions.first()
        return dict(action="answer", question_id=row.pk, answer="A", review=False,
            version=attempt.save_version, token=str(uuid4()), position=row.display_order) | overrides

    def save_url(self, attempt):
        return reverse("mock_tests:save_answer", args=[attempt.pk])


class ExecutionServiceTests(ExecutionFixture):
    def test_database_rejects_missing_deadline_and_unscored_final_status(self):
        attempt = self.ready_attempt()
        for assignment in ("expires_at = NULL", "status = 'submitted'", "last_position = 0"):
            with self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f"UPDATE mock_tests_mockattempt SET {assignment} WHERE id = %s", [attempt.pk])

    def test_deadline_uses_snapshot_and_survives_refresh(self):
        attempt = self.ready_attempt()
        self.assertEqual(attempt.expires_at, attempt.started_at + timedelta(minutes=60))
        original = attempt.expires_at
        result = refresh_attempt(self.user, attempt.pk)
        self.assertEqual(result.expires_at, original)
        self.assertFalse(result.is_finalized)

    def test_save_change_clear_review_and_position(self):
        attempt = self.ready_attempt(2)
        row = attempt.questions.first()
        result = save_response(self.user, attempt.pk, self.payload(attempt, row, review=True, position=2))
        self.assertTrue(result["ok"])
        attempt.refresh_from_db()
        row.refresh_from_db()
        self.assertEqual(attempt.last_position, 2)
        self.assertEqual(row.selected_answer, "A")
        self.assertTrue(row.marked_for_review)
        self.assertIsNotNone(row.answered_at)
        save_response(self.user, attempt.pk, self.payload(attempt, row, answer="B"))
        attempt.refresh_from_db()
        save_response(self.user, attempt.pk, self.payload(attempt, row, answer="", review=False))
        row.refresh_from_db()
        self.assertEqual(row.selected_answer, "")
        self.assertIsNone(row.answered_at)
        self.assertFalse(row.marked_for_review)

    def test_stale_save_conflicts_and_retry_is_idempotent(self):
        attempt = self.ready_attempt()
        payload = self.payload(attempt)
        first = save_response(self.user, attempt.pk, payload)
        self.assertEqual(save_response(self.user, attempt.pk, payload), first)
        stale = save_response(self.user, attempt.pk, self.payload(attempt, answer="D"))
        self.assertEqual(stale["status"], 409)
        self.assertEqual(attempt.questions.get().selected_answer, "A")
        attempt.refresh_from_db()
        self.assertEqual(attempt.save_version, 1)

    def test_bad_option_review_version_and_foreign_question_are_rejected(self):
        attempt = self.ready_attempt()
        for overrides in ({"answer": "E"}, {"answer": None}, {"review": "true"}, {"version": True}, {"position": 999}, {"action": "unknown"}, {"token": "bad"}):
            with self.assertRaises(ValidationError):
                save_response(self.user, attempt.pk, self.payload(attempt, **overrides))
        other = start_attempt(self.other_user, self.pattern)
        from django.http import Http404
        with self.assertRaises(Http404):
            save_response(self.user, attempt.pk, self.payload(attempt, question_id=other.questions.get().pk))
        self.assertEqual(attempt.questions.get().selected_answer, "")

    def test_scoring_correct_incorrect_unanswered_and_idempotency(self):
        self.section.negative_marks = Decimal("0.25")
        self.section.save()
        attempt = self.ready_attempt(3)
        rows = list(attempt.questions.all())
        save_response(self.user, attempt.pk, self.payload(attempt, rows[0], review=True))
        attempt.refresh_from_db()
        save_response(self.user, attempt.pk, self.payload(attempt, rows[1], answer="B"))
        final = submit_attempt(self.user, attempt.pk)
        self.assertEqual(final.status, "submitted")
        self.assertEqual(final.total_score, Decimal("0.75"))
        self.assertEqual(final.maximum_score, 3)
        self.assertEqual((final.correct_count, final.incorrect_count, final.unanswered_count), (1, 1, 1))
        self.assertEqual(final.percentage, Decimal("25.00"))
        section = final.section_results[str(self.section.pk)]
        self.assertEqual((section["correct"], section["incorrect"], section["unanswered"]), (1, 1, 1))
        self.assertEqual(section["score"], "0.75")
        original = final.finalized_at
        second = submit_attempt(self.user, attempt.pk)
        self.assertEqual(second.finalized_at, original)
        self.assertEqual(second.total_score, final.total_score)
        self.assertEqual(list(final.questions.values_list("awarded_marks", flat=True)), [Decimal(1), Decimal("-0.25"), Decimal(0)])

    def test_negative_total_and_section_breakdown(self):
        self.pattern.total_questions, self.pattern.total_marks = 2, Decimal("3")
        self.pattern.save()
        self.section.positive_marks = 2
        self.section.negative_marks = 3
        self.section.save()
        second = ExamPatternSection.objects.create(pattern=self.pattern, name="Second section", display_order=2, question_count=1)
        self.question()
        self.question()
        activate_pattern(self.pattern)
        attempt = start_attempt(self.user, self.pattern)
        save_response(self.user, attempt.pk, self.payload(attempt, attempt.questions.get(section=self.section), answer="D"))
        final = submit_attempt(self.user, attempt.pk)
        self.assertEqual(final.total_score, -3)
        self.assertEqual(final.percentage, Decimal("-100.00"))
        self.assertEqual(final.section_results[str(second.pk)]["unanswered"], 1)
        self.assertEqual(final.section_results[str(self.section.pk)]["maximum"], "2.00")

    def test_expiry_rejects_late_save_but_commits_finalization(self):
        attempt = self.ready_attempt()
        with patch("mock_tests.execution.timezone.now", return_value=attempt.expires_at):
            result = save_response(self.user, attempt.pk, self.payload(attempt))
        self.assertEqual(result["status"], 410)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "expired")
        self.assertEqual(attempt.unanswered_count, 1)
        self.assertEqual(attempt.finalized_at, attempt.expires_at)
        self.assertEqual(attempt.questions.get().selected_answer, "")
        self.assertEqual(submit_attempt(self.user, attempt.pk).status, "expired")

    def test_just_before_deadline_answer_counts_on_expiry(self):
        attempt = self.ready_attempt()
        with patch("mock_tests.execution.timezone.now", return_value=attempt.expires_at - timedelta(microseconds=1)):
            self.assertTrue(save_response(self.user, attempt.pk, self.payload(attempt))["ok"])
        with patch("mock_tests.execution.timezone.now", return_value=attempt.expires_at + timedelta(seconds=1)):
            final = refresh_attempt(self.user, attempt.pk)
        self.assertEqual(final.status, "expired")
        self.assertEqual(final.total_score, 1)

    def test_finalized_answers_and_results_are_immutable(self):
        attempt = self.ready_attempt()
        final = submit_attempt(self.user, attempt.pk)
        self.assertEqual(save_response(self.user, attempt.pk, self.payload(final))["status"], 410)
        row = final.questions.get()
        row.selected_answer = "A"
        with self.assertRaises(ValidationError):
            row.save(_execution=True)
        final.total_score = 100
        with self.assertRaises(ValidationError):
            final.save(_execution=True)

    def test_results_keep_original_answer_when_new_revision_is_published(self):
        attempt = self.ready_attempt()
        row = attempt.questions.get()
        save_response(self.user, attempt.pk, self.payload(attempt, row))
        question = row.question
        create_revision(question, language="en", question_text="New question", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="D", explanation="New explanation")
        publish_question(mark_reviewed(question))
        final = submit_attempt(self.user, attempt.pk)
        self.assertEqual(final.total_score, 1)
        self.assertEqual(submit_attempt(self.user, attempt.pk).total_score, 1)

    def test_submit_confirmation_version_detects_other_tab_save(self):
        attempt = self.ready_attempt()
        save_response(self.user, attempt.pk, self.payload(attempt))
        with self.assertRaises(ValidationError):
            submit_attempt(self.user, attempt.pk, expected_version=0)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "in_progress")

    def test_scoring_failure_rolls_back_partial_marks(self):
        attempt = self.ready_attempt(2)
        real_save = AttemptQuestion.save
        def failing_save(row, *args, **kwargs):
            real_save(row, *args, **kwargs)
            raise ValidationError("Scoring failure")
        with patch.object(AttemptQuestion, "save", failing_save):
            with self.assertRaises(ValidationError):
                submit_attempt(self.user, attempt.pk)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "in_progress")
        self.assertFalse(attempt.questions.filter(awarded_marks__isnull=False).exists())

    def test_idle_expiry_command(self):
        attempt = self.ready_attempt()
        with patch("mock_tests.execution.timezone.now", return_value=attempt.expires_at + timedelta(seconds=1)):
            output = StringIO()
            call_command("expire_mock_attempts", stdout=output)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, "expired")
        self.assertIn("Finalized 1", output.getvalue())


class ExecutionViewTests(ExecutionFixture):
    def test_bilingual_results_count_once_and_reveal_only_after_finalization(self):
        from questions.services import add_translation
        question = self.question()
        add_translation(question, language="bn", question_text="বাংলা প্রশ্ন", option_a="এক", option_b="দুই", option_c="তিন", option_d="চার", explanation="যাচাইকৃত ব্যাখ্যা")
        publish_question(mark_reviewed(question))
        activate_pattern(self.pattern)
        attempt = start_attempt(self.user, self.pattern)
        save_response(self.user, attempt.pk, self.payload(attempt))
        self.client.force_login(self.user)
        active = self.client.get(self.detail_url(attempt))
        self.assertContains(active, "বাংলা প্রশ্ন")
        self.assertNotContains(active, "যাচাইকৃত ব্যাখ্যা")
        self.assertContains(active, 'class="embedded-option"', count=8)
        self.assertContains(active, 'value="A" checked', count=1)
        self.assertNotContains(active, 'class="mock-answer-choices"')
        submit_attempt(self.user, attempt.pk)
        final = self.client.get(reverse("mock_tests:results", args=[attempt.pk]))
        self.assertContains(final, "যাচাইকৃত ব্যাখ্যা")
        self.assertContains(final, "Correct: 1")
        self.assertContains(final, "100.00%")
        self.assertLess(final.content.index(b'lang="en"'), final.content.index(b'lang="bn"'))

    def test_position_restored_and_submit_csrf_required(self):
        attempt = self.ready_attempt(2)
        save_response(self.user, attempt.pk, self.payload(attempt, action="position", position=2))
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        response = strict.get(self.detail_url(attempt))
        self.assertContains(response, '"position": 2')
        self.assertEqual(strict.post(reverse("mock_tests:submit", args=[attempt.pk]), {"version": 1}).status_code, 403)

    def test_active_interface_and_resume_have_no_solution_leak(self):
        attempt = self.ready_attempt()
        save_response(self.user, attempt.pk, self.payload(attempt, review=True))
        self.client.force_login(self.user)
        response = self.client.get(self.detail_url(attempt))
        self.assertContains(response, 'name="answer-')
        self.assertContains(response, 'value="A" checked')
        self.assertContains(response, "Mark for review")
        self.assertContains(response, "Question palette")
        self.assertNotContains(response, "Correct answer")
        self.assertNotContains(response, "correct-option")
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_save_json_method_csrf_and_validation(self):
        attempt = self.ready_attempt()
        self.client.force_login(self.user)
        url = self.save_url(attempt)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, data="bad", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(url, data="[]", content_type="application/json").status_code, 400)
        response = self.client.post(url, data=json.dumps(self.payload(attempt)), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        stale = self.client.post(url, data=json.dumps(self.payload(attempt, answer="D")), content_type="application/json")
        self.assertEqual(stale.status_code, 409)
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.user)
        self.assertEqual(strict.post(url, data=json.dumps(self.payload(attempt)), content_type="application/json").status_code, 403)
        page = strict.get(self.detail_url(attempt))
        csrf = strict.cookies["csrftoken"].value
        attempt.refresh_from_db()
        self.assertEqual(strict.post(url, data=json.dumps(self.payload(attempt)), content_type="application/json", HTTP_X_CSRFTOKEN=csrf).status_code, 200)

    def test_confirmation_then_results_and_review(self):
        attempt = self.ready_attempt()
        save_response(self.user, attempt.pk, self.payload(attempt, review=True))
        self.client.force_login(self.user)
        url = reverse("mock_tests:submit", args=[attempt.pk])
        response = self.client.get(url)
        self.assertContains(response, "Answered: 1")
        self.assertContains(response, "Marked for review: 1")
        result_url = reverse("mock_tests:results", args=[attempt.pk])
        self.assertRedirects(self.client.get(result_url), self.detail_url(attempt))
        self.assertEqual(self.client.post(url, {"version": 0}).status_code, 409)
        response = self.client.post(url, {"version": 1})
        self.assertRedirects(response, result_url)
        self.assertContains(self.client.get(result_url), "Correct answer: A")
        self.assertContains(self.client.get(result_url), "100.00%")
        self.assertRedirects(self.client.get(self.detail_url(attempt)), result_url)
        self.assertRedirects(self.client.post(url, {"version": 0}), result_url)

    def test_expiry_on_resume_and_status(self):
        attempt = self.ready_attempt()
        self.client.force_login(self.user)
        with patch("mock_tests.execution.timezone.now", return_value=attempt.expires_at):
            response = self.client.get(reverse("mock_tests:attempt_status", args=[attempt.pk]))
        self.assertTrue(response.json()["finalized"])
        self.assertNotIn("correct_answer", response.content.decode())
        self.assertRedirects(self.client.get(self.detail_url(attempt)), reverse("mock_tests:results", args=[attempt.pk]))

    def test_ownership_for_all_execution_routes(self):
        attempt = self.ready_attempt()
        self.client.force_login(self.other_user)
        for name in ("attempt_detail", "attempt_status", "submit", "results"):
            self.assertEqual(self.client.get(reverse(f"mock_tests:{name}", args=[attempt.pk])).status_code, 404)
        self.assertEqual(self.client.post(self.save_url(attempt), data=json.dumps(self.payload(attempt)), content_type="application/json").status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.detail_url(attempt)).status_code, 302)


class ConcurrentExecutionTests(TransactionTestCase):
    def setUp(self):
        test_patterns.PatternTests.setUpTestData.__func__(type(self))
        test_patterns.PatternTests.setUp(self)
        self.user = get_user_model().objects.create_user(username="concurrent-execution")
        test_patterns.PatternTests.question(self)
        activate_pattern(self.pattern)
        self.attempt = start_attempt(self.user, self.pattern)

    def concurrently(self, functions):
        barrier = Barrier(len(functions))
        def run(function):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return function()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=len(functions)) as executor:
            return list(executor.map(run, functions))

    def test_simultaneous_submissions_score_once(self):
        results = self.concurrently([lambda: submit_attempt(self.user, self.attempt.pk).finalized_at] * 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(MockAttempt.objects.get().unanswered_count, 1)

    def test_concurrent_save_submit_preserves_one_consistent_final_state(self):
        row = self.attempt.questions.get()
        payload = dict(action="answer", question_id=row.pk, answer="A", review=False, version=0, token=str(uuid4()), position=1)
        results = self.concurrently([lambda: save_response(self.user, self.attempt.pk, payload), lambda: submit_attempt(self.user, self.attempt.pk).pk])
        final = MockAttempt.objects.get()
        row.refresh_from_db()
        self.assertTrue(final.is_finalized)
        self.assertEqual(final.total_score, 1 if row.selected_answer == "A" else 0)
        self.assertEqual(final.correct_count, int(row.selected_answer == "A"))
        self.assertIn(results[0]["status"], (200, 410))

    def test_concurrent_saves_same_version_do_not_overwrite(self):
        row = self.attempt.questions.get()
        base = dict(action="answer", question_id=row.pk, review=False, version=0, position=1)
        results = self.concurrently([lambda: save_response(self.user, self.attempt.pk, base | {"answer": "A", "token": str(uuid4())}), lambda: save_response(self.user, self.attempt.pk, base | {"answer": "B", "token": str(uuid4())})])
        self.assertEqual(sorted(result["status"] for result in results), [200, 409])
        self.assertEqual(MockAttempt.objects.get().save_version, 1)
