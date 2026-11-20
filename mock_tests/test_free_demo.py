from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from billing.models import FreeExamSelection, FreeMockSelection, UserSubscription
from billing.test_usage import free_configuration
from exams.models import ExamStage
from practice import tests as practice_tests
from questions.services import create_revision, mark_reviewed, publish_question
from .models import ExamPattern, ExamPatternSection, MockAttempt, MockSet, MockSetQuestion
from .services import (activate_pattern, deactivate_pattern, publish_free_demo,
                       retire_free_demo, start_attempt, available_patterns)
from .execution import submit_attempt
from .testing import premium_user


def pattern_for(exam, name, *, free_demo=False):
    stage = ExamStage.objects.create(exam=exam, name=name, code=name)
    pattern = ExamPattern.objects.create(exam=exam, stage=stage, name=name, total_questions=2,
        total_marks=2, duration_minutes=30, is_free_demo=free_demo)
    ExamPatternSection.objects.create(pattern=pattern, name="Section", language_mode="en", question_count=2, display_order=1)
    return pattern


class SharedFreeDemoTests(practice_tests.PracticeFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.pool = [cls.question(cls) for _ in range(6)]
        cls.other_pool = [cls.question(cls, exam=cls.other_exam) for _ in range(2)]

    def signature(self, rows):
        return list(rows.values_list("question_id", "question_revision_id", "section_id", "display_order", "positive_marks", "negative_marks"))

    def demo(self, name="Demo"):
        pattern = pattern_for(self.exam, name)
        return publish_free_demo(pattern)

    def test_expired_demo_blocks_new_starts_and_preserves_existing_attempt(self):
        pattern = self.demo()
        attempt = start_attempt(self.user, pattern)
        self.subject.question_freshness_years = 2
        self.subject.save(update_fields=["question_freshness_years"])
        today = timezone.localdate()
        for question in self.pool:
            question.expires_on = today
            question.save(update_fields=["expires_on"])
        self.assertNotIn(pattern, available_patterns(pk=pattern.pk))
        with self.assertRaisesMessage(ValidationError, "Retire it and publish a new pattern"):
            publish_free_demo(pattern)
        with self.assertRaisesMessage(ValidationError, "currently unavailable"):
            start_attempt(self.other_user, pattern)
        self.assertEqual(start_attempt(self.user, pattern).pk, attempt.pk)
        self.assertEqual(attempt.questions.count(), 2)

    def test_default_is_not_demo_and_free_cannot_start_an_undesignated_pattern(self):
        pattern = activate_pattern(pattern_for(self.exam, "Premium"))
        self.assertFalse(pattern.is_free_demo)
        with self.assertRaisesMessage(ValidationError, "Free Demo"):
            start_attempt(self.user, pattern)
        self.assertFalse(FreeExamSelection.objects.exists())
        self.assertFalse(MockAttempt.objects.exists())

    def test_draft_checkbox_activation_publishes_once(self):
        pattern = activate_pattern(pattern_for(self.exam, "Checkbox demo", free_demo=True))
        published = MockSet.objects.get(pattern=pattern)
        self.assertEqual(published.questions.count(), 2)
        with patch("mock_tests.services.select_questions", side_effect=AssertionError("Must not republish")):
            publish_free_demo(pattern)
        self.assertEqual(MockSet.objects.count(), 1)
        self.assertEqual(published.configuration["duration_minutes"], 30)

    def test_all_free_users_and_retakes_copy_identical_questions_and_marks(self):
        pattern = self.demo()
        expected = self.signature(pattern.published_set.questions)
        with patch("mock_tests.services.select_questions", side_effect=AssertionError("Free must not draw")):
            first = start_attempt(self.user, pattern)
            other = start_attempt(self.other_user, pattern)
            self.assertEqual(first.mock_set_id, other.mock_set_id)
            self.assertEqual(self.signature(first.questions), expected)
            self.assertEqual(self.signature(other.questions), expected)
            submit_attempt(self.user, first.pk)
            retake = start_attempt(self.user, pattern)
            self.assertNotEqual(retake.pk, first.pk)
            self.assertEqual(self.signature(retake.questions), expected)
            self.assertEqual(first.configuration, retake.configuration)
            submit_attempt(self.user, retake.pk)
            third = start_attempt(self.user, pattern)
            self.assertEqual(self.signature(third.questions), expected)
        first.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(first.status, "submitted")
        self.assertEqual(other.status, "in_progress")
        self.assertIsNotNone(first.total_score)
        self.assertIsNone(other.total_score)
        self.assertFalse(FreeMockSelection.objects.exists())

    def test_later_revision_and_new_candidates_do_not_change_frozen_content(self):
        pattern = self.demo()
        original = pattern.published_set.questions.first()
        question = original.question
        create_revision(question, language="en", question_text="Changed edition", option_a="A", option_b="B",
                        option_c="C", option_d="D", correct_answer="D")
        publish_question(mark_reviewed(question))
        self.question()
        attempt = start_attempt(self.user, pattern)
        self.assertEqual(attempt.questions.get(question=question).question_revision_id, original.question_revision_id)
        self.assertEqual(self.signature(attempt.questions), self.signature(pattern.published_set.questions))

    def test_frozen_pattern_and_sections_cannot_change_after_deactivation(self):
        pattern = deactivate_pattern(self.demo())
        pattern.duration_minutes = 60
        with self.assertRaises(ValidationError):
            pattern.save()
        section = pattern.sections.get()
        section.name = "Changed"
        with self.assertRaises(ValidationError):
            section.save()
        with self.assertRaises(ValidationError):
            section.delete()
        mock_set = pattern.published_set
        mock_set.configuration["duration_minutes"] = 60
        with self.assertRaises(ValidationError):
            mock_set.save(_publication=True)
        with self.assertRaises(ValidationError):
            MockSetQuestion.objects.all().update(display_order=10)

    def test_service_and_database_allow_only_one_active_demo_across_stages(self):
        first = self.demo()
        second = pattern_for(self.exam, "Second stage demo")
        with self.assertRaisesMessage(ValidationError, "existing active Free Demo"):
            publish_free_demo(second)
        activate_pattern(second)
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE mock_tests_exampattern SET is_free_demo = TRUE WHERE id = %s", [second.pk])
        self.assertEqual(ExamPattern.objects.filter(exam=self.exam, is_free_demo=True, status="active").get(), first)

    def test_free_exam_selection_still_blocks_other_exam_demo(self):
        first = self.demo()
        other = publish_free_demo(pattern_for(self.other_exam, "Other exam"))
        start_attempt(self.user, first)
        with self.assertRaisesMessage(ValidationError, "Free exam"):
            start_attempt(self.user, other)
        self.assertEqual(FreeExamSelection.objects.get(user=self.user).exam, self.exam)

    def test_legacy_selection_does_not_block_designated_demo_or_get_rewritten(self):
        legacy = activate_pattern(pattern_for(self.exam, "Legacy pattern"))
        selection = FreeMockSelection.objects.create(user=self.user, pattern=legacy)
        FreeExamSelection.objects.create(user=self.user, exam=self.exam)
        attempt = start_attempt(self.user, self.demo())
        self.assertIsNotNone(attempt.mock_set_id)
        selection.refresh_from_db()
        self.assertEqual(selection.pattern_id, legacy.pk)

    def test_premium_keeps_random_selection_even_on_demo_and_other_exams(self):
        pattern = self.demo()
        premium_user(self.user)
        choices = [[question.pk for question in self.pool[:2]], [question.pk for question in self.pool[2:4]]]
        with patch("mock_tests.services.select_questions", side_effect=[[choices[0]], [choices[1]]]) as selector:
            first = start_attempt(self.user, pattern)
            submit_attempt(self.user, first.pk)
            second = start_attempt(self.user, pattern)
        self.assertEqual(selector.call_count, 2)
        self.assertIsNone(first.mock_set_id)
        self.assertIsNone(second.mock_set_id)
        self.assertNotEqual(self.signature(first.questions), self.signature(second.questions))
        other = activate_pattern(pattern_for(self.other_exam, "Other premium pattern"))
        self.assertEqual(start_attempt(self.user, other).pattern_id, other.pk)
        self.assertFalse(FreeExamSelection.objects.exists())

    def test_legacy_unfinished_attempt_and_results_survive_designation(self):
        pattern = activate_pattern(pattern_for(self.exam, "Existing active pattern"))
        premium_user(self.user)
        old = start_attempt(self.user, pattern)
        old_rows = self.signature(old.questions)
        publish_free_demo(pattern)
        UserSubscription.objects.filter(user=self.user).update(status="cancelled")
        self.assertEqual(start_attempt(self.user, pattern).pk, old.pk)
        self.assertEqual(self.signature(old.questions), old_rows)
        submit_attempt(self.user, old.pk)
        new = start_attempt(self.user, ExamPattern.objects.get(pk=pattern.pk))
        self.assertIsNotNone(new.mock_set_id)
        old.refresh_from_db()
        self.assertIsNone(old.mock_set_id)
        self.assertEqual(old.status, "submitted")
        self.assertEqual(self.signature(old.questions), old_rows)

    def test_retirement_preserves_attempts_and_allows_another_shared_demo(self):
        first = self.demo()
        attempt = start_attempt(self.user, first)
        retire_free_demo(first)
        self.assertEqual(start_attempt(self.user, first).pk, attempt.pk)
        submit_attempt(self.user, attempt.pk)
        with self.assertRaises(ValidationError):
            start_attempt(self.user, ExamPattern.objects.get(pk=first.pk))
        new = self.demo("Replacement demo")
        self.assertEqual(start_attempt(self.user, new).mock_set_id, new.published_set.pk)
        self.assertEqual(MockSet.objects.count(), 2)

    def test_failure_during_publication_rolls_back_designation_and_rows(self):
        pattern = pattern_for(self.exam, "Failed publication")
        with patch("mock_tests.services.MockSetQuestion.save", side_effect=ValidationError("write failed")):
            with self.assertRaises(ValidationError):
                publish_free_demo(pattern)
        pattern.refresh_from_db()
        self.assertEqual(pattern.status, "draft")
        self.assertFalse(pattern.is_free_demo)
        self.assertFalse(MockSet.objects.exists())

    def test_database_freezes_snapshots_and_rejects_extra_questions(self):
        pattern = self.demo()
        mock_set = pattern.published_set
        for sql, pk in (
            ("UPDATE mock_tests_mockset SET configuration = '{}'::jsonb WHERE id = %s", mock_set.pk),
            ("DELETE FROM mock_tests_mocksetquestion WHERE mock_set_id = %s", mock_set.pk),
            ("UPDATE mock_tests_exampattern SET duration_minutes = 60 WHERE id = %s", pattern.pk),
        ):
            with self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, [pk])
        used = set(mock_set.questions.values_list("question_id", flat=True))
        extra = next(question for question in self.pool if question.pk not in used)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MockSetQuestion(mock_set=mock_set, section=pattern.sections.get(), question=extra,
                question_revision=extra.published_revision, display_order=3, positive_marks=1, negative_marks=0).save(_publication=True)

    def test_database_rejects_incomplete_publication_at_commit_boundary(self):
        pattern = pattern_for(self.exam, "Incomplete")
        with self.assertRaises(IntegrityError), transaction.atomic():
            MockSet(pattern=pattern, configuration={"total_questions": 2}).save(_publication=True)
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS mock_set_complete IMMEDIATE")
        self.assertFalse(MockSet.objects.exists())

    def test_retired_publication_can_be_reused_without_redrawing(self):
        pattern = self.demo()
        original = self.signature(pattern.published_set.questions)
        retire_free_demo(pattern)
        deactivate_pattern(pattern)
        with patch("mock_tests.services.select_questions", side_effect=AssertionError("Must reuse publication")):
            reactivated = publish_free_demo(pattern)
        self.assertTrue(reactivated.is_active)
        self.assertEqual(self.signature(reactivated.published_set.questions), original)

    def test_withdrawn_exam_membership_blocks_new_attempt_without_reselection(self):
        from questions.models import QuestionExam
        pattern = self.demo()
        original = pattern.published_set.questions.first()
        QuestionExam.objects.filter(question_id=original.question_id, exam=self.exam).delete()
        with self.assertRaisesMessage(ValidationError, "currently unavailable"):
            start_attempt(self.user, pattern)
        self.assertNotIn(pattern, available_patterns())
        self.assertFalse(MockAttempt.objects.exists())
        self.assertEqual(pattern.published_set.questions.count(), 2)

    def test_admin_exposes_designation_and_permission_gated_publication(self):
        pattern = activate_pattern(pattern_for(self.exam, "Admin demo"))
        model_admin = admin.site._registry[ExamPattern]
        self.assertIn("is_free_demo", model_admin.list_display)
        staff = get_user_model().objects.create_user(username="demo-publisher", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="change_exampattern"),
                                   Permission.objects.get(codename="view_exampattern"))
        self.client.force_login(staff)
        url = reverse("admin:mock_tests_exampattern_changelist")
        self.assertEqual(self.client.post(url, {"action": "publish_demo_selected", "_selected_action": pattern.pk}).status_code, 302)
        pattern.refresh_from_db()
        self.assertTrue(pattern.is_free_demo)
        self.assertTrue(MockSet.objects.filter(pattern=pattern).exists())
        request = RequestFactory().get(url)
        viewer = get_user_model().objects.create_user(username="demo-viewer", is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(codename="view_exampattern"))
        request.user = viewer
        self.assertNotIn("publish_demo_selected", model_admin.get_actions(request))
        for model in (MockSet, MockSetQuestion):
            self.assertFalse(admin.site._registry[model].has_add_permission(request))
            self.assertFalse(admin.site._registry[model].has_change_permission(request))
            self.assertFalse(admin.site._registry[model].has_delete_permission(request))


class ConcurrentDemoTests(TransactionTestCase):
    def setUp(self):
        free_configuration()
        practice_tests.PracticeFixture.setUpTestData.__func__(type(self))
        for _ in range(4):
            practice_tests.PracticeFixture.question(self)

    def race(self, functions):
        barrier = Barrier(2)
        def run(function):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return function().pk
                except ValidationError:
                    return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(run, functions))

    def test_concurrent_publications_for_one_exam_cannot_both_win(self):
        first = pattern_for(self.exam, "First")
        second = pattern_for(self.exam, "Second")
        result = self.race([lambda: publish_free_demo(first), lambda: publish_free_demo(second)])
        self.assertEqual(result.count(None), 1)
        self.assertEqual(MockSet.objects.count(), 1)
        self.assertEqual(ExamPattern.objects.filter(status="active", is_free_demo=True).count(), 1)

    def test_concurrent_users_copy_one_publication(self):
        pattern = publish_free_demo(pattern_for(self.exam, "Shared"))
        self.race([lambda: start_attempt(self.user, pattern), lambda: start_attempt(self.other_user, pattern)])
        attempts = list(MockAttempt.objects.order_by("pk"))
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0].mock_set_id, attempts[1].mock_set_id)
        self.assertEqual(list(attempts[0].questions.values_list("question_id", "question_revision_id", "display_order")),
                         list(attempts[1].questions.values_list("question_id", "question_revision_id", "display_order")))

    def test_publication_and_first_free_start_can_race_without_deadlock(self):
        pattern = activate_pattern(pattern_for(self.exam, "Concurrent designation"))
        results = self.race([lambda: publish_free_demo(pattern), lambda: start_attempt(self.user, pattern)])
        self.assertIsNotNone(results[0])
        self.assertTrue(ExamPattern.objects.get(pk=pattern.pk).is_free_demo)
        self.assertEqual(MockSet.objects.count(), 1)


class DemoMigrationTests(TransactionTestCase):
    def test_additive_upgrade_preserves_old_attempt_rows_and_subscriptions(self):
        practice_tests.PracticeFixture.setUpTestData.__func__(type(self))
        for _ in range(2):
            practice_tests.PracticeFixture.question(self)
        premium_user(self.user)
        pattern = activate_pattern(pattern_for(self.exam, "Existing production pattern"))
        attempt = start_attempt(self.user, pattern)
        original_configuration = attempt.configuration
        original_rows = list(attempt.questions.values_list("pk", "question_id", "question_revision_id", "display_order"))
        subscription = UserSubscription.objects.get(user=self.user)
        old_term = (subscription.starts_at, subscription.ends_at, subscription.status)
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        executor.migrate([("mock_tests", "0006_sectionselectionrule_manualrulequestion_and_more")])
        try:
            historical_apps = executor.loader.project_state([("mock_tests", "0006_sectionselectionrule_manualrulequestion_and_more")]).apps
            self.assertEqual(historical_apps.get_model("mock_tests", "MockAttempt").objects.get(pk=attempt.pk).configuration, original_configuration)
            MigrationExecutor(connection).migrate(latest)
            pattern.refresh_from_db()
            attempt.refresh_from_db()
            subscription.refresh_from_db()
            self.assertFalse(pattern.is_free_demo)
            self.assertIsNone(attempt.mock_set_id)
            self.assertEqual(attempt.configuration, original_configuration)
            self.assertEqual(list(attempt.questions.values_list("pk", "question_id", "question_revision_id", "display_order")), original_rows)
            self.assertEqual((subscription.starts_at, subscription.ends_at, subscription.status), old_term)
            self.assertFalse(MockSet.objects.exists())
        finally:
            MigrationExecutor(connection).migrate(latest)
