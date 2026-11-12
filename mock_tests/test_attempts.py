from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from questions.models import QuestionExam
from questions.services import add_translation, create_revision, mark_reviewed, publish_question
from previous_year.models import PaperQuestion, PreviousYearPaper
from . import test_patterns
from .models import AttemptQuestion, ExamPattern, ExamPatternSection, MockAttempt
from .services import activate_pattern, deactivate_pattern, select_questions, start_attempt


class AttemptFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        test_patterns.PatternTests.setUpTestData.__func__(cls)
        cls.user = get_user_model().objects.create_user(username="student", password="student-password")
        cls.other_user = get_user_model().objects.create_user(username="other")

    def setUp(self):
        test_patterns.PatternTests.setUp(self)

    question = test_patterns.PatternTests.question

    def ready(self):
        question = self.question()
        activate_pattern(self.pattern)
        return question

    def start_url(self):
        return reverse("mock_tests:start", args=[self.pattern.pk])

    def detail_url(self, attempt):
        return reverse("mock_tests:attempt_detail", args=[attempt.pk])


class AttemptLanguageTests(AttemptFixture):
    def bilingual_pattern(self):
        question = self.question()
        add_translation(question, language="bn", question_text="Bengali edition", option_a="BN A",
                        option_b="BN B", option_c="BN C", option_d="BN D")
        question = publish_question(mark_reviewed(question))
        self.section.language_mode = "mixed"
        self.section.save()
        activate_pattern(self.pattern)
        return question

    def test_selected_language_is_rendered_on_server_and_preserved_on_resume(self):
        self.bilingual_pattern()
        self.client.force_login(self.user)
        for language in ("en", "bn", "both"):
            with self.subTest(language=language):
                user = get_user_model().objects.create_user(username="language_" + language)
                self.client.force_login(user)
                attempt = start_attempt(user, self.pattern, language=language)
                response = self.client.get(self.detail_url(attempt))
                for code in ("en", "bn"):
                    marker = f'lang="{code}" aria-label='
                    if language in (code, "both"):
                        self.assertContains(response, marker)
                    else:
                        self.assertNotContains(response, marker)
                resumed = start_attempt(user, self.pattern, language="both")
                self.assertEqual(resumed.pk, attempt.pk)
                self.assertEqual(resumed.configuration["language"], language)

    def test_invalid_or_unavailable_language_does_not_create_attempt(self):
        self.ready()
        for language in ("invalid", "bn"):
            with self.subTest(language=language), self.assertRaises(ValidationError):
                start_attempt(self.user, self.pattern, language=language)
        self.assertFalse(MockAttempt.objects.exists())


class AttemptServiceTests(AttemptFixture):
    def test_section_marks_and_labels_are_snapshotted(self):
        from decimal import Decimal
        self.question()
        self.pattern.total_marks = Decimal("2.50")
        self.pattern.save()
        self.section.positive_marks = Decimal("2.50")
        self.section.negative_marks = Decimal("0.75")
        self.section.save()
        activate_pattern(self.pattern)
        attempt = start_attempt(self.user, self.pattern)
        row = attempt.questions.get()
        self.assertEqual(row.positive_marks, Decimal("2.50"))
        self.assertEqual(row.negative_marks, Decimal("0.75"))
        self.assertEqual(attempt.configuration["sections"][0]["negative_marks"], "0.75")
        self.exam.name = "Later exam name"
        self.exam.save()
        self.client.force_login(self.user)
        response = self.client.get(self.detail_url(attempt))
        self.assertContains(response, "Exam")
        self.assertNotContains(response, "Later exam name")

    def test_eligibility_loss_during_start_recheck_creates_nothing(self):
        question = self.ready()
        with patch("mock_tests.services.eligible_question_ids", side_effect=[{question.pk}, set()]):
            with self.assertRaises(ValidationError):
                start_attempt(self.user, self.pattern)
        self.assertFalse(MockAttempt.objects.exists())
        self.assertFalse(AttemptQuestion.objects.exists())

    def test_start_persists_configuration_questions_and_effective_marks(self):
        question = self.ready()
        attempt = start_attempt(self.user, self.pattern)
        self.assertEqual(attempt.user, self.user)
        self.assertEqual(attempt.status, "in_progress")
        self.assertIsNotNone(attempt.started_at)
        self.assertIsNotNone(attempt.created_at)
        self.assertEqual(attempt.configuration["name"], "Pattern")
        self.assertEqual(attempt.configuration["total_questions"], 1)
        row = attempt.questions.get()
        self.assertEqual(row.question_revision_id, question.published_revision_id)
        self.assertEqual(row.display_order, 1)
        self.assertEqual(row.positive_marks, 1)
        self.assertEqual(row.negative_marks, 0)
        self.assertEqual(row.section_id, self.section.pk)

    def test_repeated_start_returns_same_fixed_attempt(self):
        self.ready()
        first = start_attempt(self.user, self.pattern)
        ids = list(first.questions.values_list("question_revision_id", flat=True))
        second = start_attempt(self.user, self.pattern)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(list(second.questions.values_list("question_revision_id", flat=True)), ids)
        self.assertEqual(MockAttempt.objects.count(), 1)
        deactivate_pattern(self.pattern)
        self.assertEqual(start_attempt(self.user, self.pattern).pk, first.pk)

    def test_ineligible_or_inactive_pattern_leaves_no_attempt(self):
        self.question(published=False)
        with self.assertRaises(ValidationError):
            start_attempt(self.user, self.pattern)
        question = self.ready()
        QuestionExam.objects.filter(question=question).delete()
        with self.assertRaises(ValidationError):
            start_attempt(self.user, self.pattern)
        self.assertFalse(MockAttempt.objects.exists())
        self.assertFalse(AttemptQuestion.objects.exists())

    def test_failure_after_first_question_rolls_back_everything(self):
        self.ready()
        real_save = AttemptQuestion.save
        def fail_after_save(row, *args, **kwargs):
            real_save(row, *args, **kwargs)
            raise ValidationError("Simulated write failure")
        with patch.object(AttemptQuestion, "save", fail_after_save):
            with self.assertRaises(ValidationError):
                start_attempt(self.user, self.pattern)
        self.assertFalse(MockAttempt.objects.exists())
        self.assertFalse(AttemptQuestion.objects.exists())

    def test_bilingual_is_one_question_and_snapshot_is_pinned(self):
        question = self.question()
        add_translation(question, language="bn", question_text="Bengali translation", option_a="One", option_b="Two", option_c="Three", option_d="Four", explanation="Hidden Bengali explanation")
        question = publish_question(mark_reviewed(question))
        activate_pattern(self.pattern)
        attempt = start_attempt(self.user, self.pattern)
        revision_id = question.published_revision_id
        create_revision(question, language="en", question_text="Later content", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="C", explanation="Later explanation")
        publish_question(mark_reviewed(question))
        self.assertEqual(attempt.questions.count(), 1)
        self.assertEqual(attempt.questions.get().question_revision_id, revision_id)
        self.client.force_login(self.user)
        response = self.client.get(self.detail_url(attempt))
        self.assertContains(response, "Question?")
        self.assertContains(response, "Bengali translation")
        self.assertNotContains(response, "Later content")
        self.assertNotContains(response, "Hidden Bengali explanation")
        self.assertLess(response.content.index(b'lang="en"'), response.content.index(b'lang="bn"'))

    def test_selection_handles_overlap_without_starving_restricted_section(self):
        first, second = self.question(), self.question()
        self.pattern.total_questions = 2
        self.pattern.total_marks = 2
        self.pattern.save()
        restricted = ExamPatternSection.objects.create(language_mode="en", pattern=self.pattern, name="Restricted", display_order=2, question_count=1, topic=self.topic)
        second.topic = None
        second.save()
        activate_pattern(self.pattern)
        attempt = start_attempt(self.user, self.pattern)
        self.assertEqual(attempt.questions.get(section=restricted).question_id, first.pk)
        self.assertEqual(attempt.questions.get(section=self.section).question_id, second.pk)
        self.assertEqual(list(attempt.questions.values_list("display_order", flat=True)), [1, 2])

    def test_overlap_insufficiency_and_selection_function(self):
        self.question()
        self.pattern.total_questions = 2
        self.pattern.total_marks = 2
        self.pattern.save()
        second = ExamPatternSection.objects.create(language_mode="en", pattern=self.pattern, name="Other", display_order=2, question_count=1)
        with self.assertRaises(ValidationError):
            select_questions([self.section, second])
        self.assertFalse(MockAttempt.objects.exists())

    def test_pattern_and_sections_with_attempts_stay_frozen(self):
        self.ready()
        attempt = start_attempt(self.user, self.pattern)
        pattern = deactivate_pattern(self.pattern)
        pattern.name = "Changed name"
        with self.assertRaises(ValidationError):
            pattern.save()
        self.section.name = "Changed section"
        with self.assertRaises(ValidationError):
            self.section.save()
        with self.assertRaises(ValidationError):
            self.section.delete()
        attempt.refresh_from_db()
        self.assertEqual(attempt.configuration["name"], "Pattern")
        self.assertEqual(attempt.configuration["sections"][0]["name"], "Section")

    def test_attempt_and_question_snapshots_cannot_be_edited_or_deleted(self):
        self.ready()
        attempt = start_attempt(self.user, self.pattern)
        attempt.configuration["name"] = "Changed"
        with self.assertRaises(ValidationError):
            attempt.save()
        row = attempt.questions.get()
        row.negative_marks = 5
        with self.assertRaises(ValidationError):
            row.save()
        with self.assertRaises(ValidationError):
            row.delete()
        with self.assertRaises(ValidationError):
            MockAttempt.objects.all().delete()
        with self.assertRaises(ValidationError):
            AttemptQuestion.objects.all().update(positive_marks=10)

    def test_database_prevents_duplicate_open_attempt_and_master_question(self):
        self.ready()
        attempt = start_attempt(self.user, self.pattern)
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO mock_tests_mockattempt (user_id, pattern_id, status, created_at, started_at, configuration) SELECT user_id, pattern_id, status, created_at, started_at, configuration FROM mock_tests_mockattempt WHERE id = %s", [attempt.pk])
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO mock_tests_attemptquestion (attempt_id, section_id, question_id, question_revision_id, display_order, positive_marks, negative_marks) SELECT attempt_id, section_id, question_id, question_revision_id, 2, positive_marks, negative_marks FROM mock_tests_attemptquestion WHERE attempt_id = %s", [attempt.pk])

    def test_previous_year_revision_association_is_unchanged(self):
        question = self.ready()
        paper = PreviousYearPaper.objects.create(exam=self.exam, year=2019, paper_name="Original")
        row = PaperQuestion.objects.create(paper=paper, question_revision=question.published_revision, question_number="40", display_order=1)
        start_attempt(self.user, self.pattern)
        row.refresh_from_db()
        self.assertEqual(row.question_revision_id, question.published_revision_id)
        self.assertEqual(row.question_number, "40")


class AttemptViewTests(AttemptFixture):
    def test_guest_redirect_and_post_csrf_enforcement(self):
        self.ready()
        for url in (reverse("mock_tests:index"), self.start_url()):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("next=", response.url)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.start_url()).status_code, 403)
        self.assertFalse(MockAttempt.objects.exists())

    def test_navigation_and_get_start_never_creates_attempt(self):
        self.ready()
        self.client.force_login(self.user)
        for url, text in ((reverse("mock_tests:index"), "Authority"),
            (reverse("mock_tests:exams", args=[self.exam.authority.slug]), self.exam.name),
            (reverse("mock_tests:patterns", args=[self.exam.authority.slug, self.exam.slug]), "Pattern"),
            (self.start_url(), "Start Test")):
            self.assertContains(self.client.get(url), text)
        self.assertFalse(MockAttempt.objects.exists())

    def test_start_resume_and_ownership(self):
        question = self.question()
        add_translation(question, language="bn", question_text="Bengali question", option_a="BN A", option_b="BN B", option_c="BN C", option_d="BN D")
        publish_question(mark_reviewed(question))
        self.section.language_mode = "mixed"
        self.section.save()
        activate_pattern(self.pattern)
        self.client.force_login(self.user)
        response = self.client.post(self.start_url(), {"language": "bn"})
        attempt = MockAttempt.objects.get()
        self.assertRedirects(response, self.detail_url(attempt))
        self.assertRedirects(self.client.post(self.start_url()), self.detail_url(attempt))
        self.assertRedirects(self.client.get(self.start_url()), self.detail_url(attempt))
        self.assertEqual(self.client.get(self.detail_url(attempt)).context["preferred_language"], "bn")
        self.assertEqual(attempt.configuration["language"], "bn")
        # The preference survives a new login, without relying on the old browser session.
        self.client.logout()
        self.client.force_login(self.user)
        response = self.client.get(self.detail_url(attempt))
        self.assertContains(response, "Bengali question")
        self.assertNotContains(response, 'lang="en" aria-label="English version"')
        self.assertEqual(MockAttempt.objects.count(), 1)
        self.assertContains(self.client.get(reverse("mock_tests:index")), "Resume Pattern")
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(self.detail_url(attempt)).status_code, 404)
        self.assertEqual(self.client.post(self.detail_url(attempt)).status_code, 405)

    def test_invalid_patterns_hidden_and_pool_loss_fails_gracefully(self):
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("mock_tests:index")), "Authority")
        self.assertEqual(self.client.get(self.start_url()).status_code, 404)
        question = self.ready()
        QuestionExam.objects.filter(question=question).delete()
        url = reverse("mock_tests:patterns", args=[self.exam.authority.slug, self.exam.slug])
        self.assertNotContains(self.client.get(url), "Start Test")
        self.assertEqual(self.client.post(self.start_url()).status_code, 400)
        self.assertFalse(MockAttempt.objects.exists())

    def test_execution_controls_render_without_answers_or_explanations(self):
        self.ready()
        attempt = start_attempt(self.user, self.pattern)
        self.client.force_login(self.user)
        response = self.client.get(self.detail_url(attempt))
        self.assertContains(response, "Question 1")
        self.assertNotContains(response, "Correct answer")
        self.assertNotContains(response, "Show Answer")
        self.assertNotContains(response, "correct-option")
        self.assertContains(response, 'type="radio"', count=4)


class ConcurrentStartTests(TransactionTestCase):
    def setUp(self):
        test_patterns.PatternTests.setUpTestData.__func__(type(self))
        test_patterns.PatternTests.setUp(self)
        self.user = get_user_model().objects.create_user(username="concurrent")
        test_patterns.PatternTests.question(self)
        activate_pattern(self.pattern)

    def test_simultaneous_starts_create_exactly_one_attempt(self):
        barrier = Barrier(2)
        def start():
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.user.pk)
                pattern = ExamPattern.objects.get(pk=self.pattern.pk)
                barrier.wait(timeout=10)
                return start_attempt(user, pattern).pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: start(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(MockAttempt.objects.count(), 1)
        self.assertEqual(AttemptQuestion.objects.count(), 1)
