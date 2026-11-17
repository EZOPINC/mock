from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib import import_module
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from mock_tests.execution import submit_attempt
from mock_tests.models import ExamPattern, ExamPatternSection, MockAttempt
from mock_tests.services import activate_pattern, start_attempt
from practice import tests as practice_tests
from practice.models import PracticeSession
from practice.services import start_session, submit_answer
from .models import (FreeExamSelection, FreeMockSelection, FreeQuestionUsage,
                     PlanEntitlement, SubscriptionPlan, UserSubscription)


def free_configuration():
    """TransactionTestCase flushes migration seed data between tests."""
    plan, _ = SubscriptionPlan.objects.get_or_create(code="free", defaults={
        "name": "Free", "tier": "free", "price": 0, "is_active": True})
    for feature, limit in (("mock", 1), ("practice", 50)):
        PlanEntitlement.objects.get_or_create(plan=plan, feature=feature,
                                             defaults={"usage_limit": limit})


def make_pattern(exam, name, *, free_demo=False):
    from exams.models import ExamStage
    stage = ExamStage.objects.create(exam=exam, name=name, code=name.replace(" ", "-"))
    pattern = ExamPattern.objects.create(exam=exam, stage=stage, name=name, duration_minutes=60, is_free_demo=free_demo,
                                        total_questions=1, total_marks=1)
    ExamPatternSection.objects.create(pattern=pattern, name="Section", language_mode="en",
                                      question_count=1, display_order=1)
    activate_pattern(pattern)
    return pattern


def difficulty_question(fixture, difficulty):
    from questions.models import QuestionExam
    from questions.services import create_question, mark_reviewed, publish_question
    question = create_question(subject=fixture.subject, topic=fixture.topic, difficulty_level=difficulty,
        revision={"language": "en", "question_text": "Allowance question", "option_a": "A", "option_b": "B",
                  "option_c": "C", "option_d": "D", "correct_answer": "A"})
    QuestionExam.objects.create(question=question, exam=fixture.exam)
    return publish_question(mark_reviewed(question))


class FreeUsageTests(practice_tests.PracticeFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.easy = [difficulty_question(cls, "easy") for _ in range(50)]
        cls.hard = difficulty_question(cls, "hard")
        cls.other_question = cls.question(cls, exam=cls.other_exam)
        cls.pattern = make_pattern(cls.exam, "First set", free_demo=True)
        cls.second_pattern = make_pattern(cls.exam, "Second set")
        cls.other_pattern = make_pattern(cls.other_exam, "Other exam set", free_demo=True)

    def premium(self):
        plan = SubscriptionPlan.objects.get(code="premium-30")
        plan.is_active = True
        plan.save()
        return UserSubscription.objects.create(user=self.user, plan=plan,
            starts_at=timezone.now() - timedelta(days=1), ends_at=timezone.now() + timedelta(days=29))

    def test_fifty_distinct_then_fifty_first_blocked_and_revisits_free(self):
        first = self.session(difficulty="easy", count="50")
        self.assertEqual(first.questions.count(), 50)
        self.assertEqual(FreeQuestionUsage.objects.filter(user=self.user).count(), 50)
        with self.assertRaisesMessage(ValidationError, "Premium"):
            self.session(difficulty="hard")
        revisit = self.session(difficulty="easy", count="50")
        self.assertEqual(revisit.questions.count(), 50)
        self.assertEqual(FreeQuestionUsage.objects.filter(user=self.user).count(), 50)
        self.assertEqual(PracticeSession.objects.count(), 2)

    def test_available_pool_allocates_only_the_default_first_batch(self):
        session = self.session()
        self.assertEqual(session.questions.count(), 10)
        self.assertEqual(session.configuration["total_questions"], 10)
        self.assertEqual(FreeQuestionUsage.objects.count(), 10)

    def test_oversized_numeric_request_rolls_back_exam_and_usage(self):
        PlanEntitlement.objects.filter(plan__tier="free", feature="practice").update(usage_limit=9)
        with self.assertRaisesMessage(ValidationError, "Premium"):
            self.session(count="10")
        self.assertFalse(FreeExamSelection.objects.exists())
        self.assertFalse(FreeQuestionUsage.objects.exists())
        self.assertFalse(PracticeSession.objects.exists())
        self.assertEqual(self.session().questions.count(), 9)

    def test_new_revision_and_translation_reuse_master_allowance(self):
        from questions.services import add_translation, create_revision, mark_reviewed, publish_question
        first = self.session(difficulty="hard")
        original_revision = first.questions.get().question_revision_id
        create_revision(self.hard, language="en", question_text="Updated question", option_a="A",
                        option_b="B", option_c="C", option_d="D", correct_answer="A")
        add_translation(self.hard, language="bn", question_text="Bengali question", option_a="A",
                        option_b="B", option_c="C", option_d="D")
        publish_question(mark_reviewed(self.hard))
        second = self.session(difficulty="hard", language="bn")
        self.assertNotEqual(second.questions.get().question_revision_id, original_revision)
        self.assertEqual(second.questions.get().question_id, self.hard.pk)
        self.assertEqual(FreeQuestionUsage.objects.count(), 1)

    def test_last_slot_and_previously_delivered_master_ids(self):
        PlanEntitlement.objects.filter(plan__tier="free", feature="practice").update(usage_limit=1)
        first = self.session(difficulty="hard")
        row = first.questions.get()
        self.assertEqual(row.question_id, self.hard.pk)
        submit_answer(self.user, first.pk, row.pk, "A")
        submit_answer(self.user, first.pk, row.pk, "A")
        self.assertEqual(self.session(difficulty="hard").questions.get().question_id, self.hard.pk)
        self.assertEqual(FreeQuestionUsage.objects.count(), 1)
        with self.assertRaises(ValidationError):
            self.session(difficulty="easy")

    def test_mock_retakes_and_second_distinct_set_blocked(self):
        first = start_attempt(self.user, self.pattern)
        self.assertEqual(start_attempt(self.user, self.pattern).pk, first.pk)
        submit_attempt(self.user, first.pk)
        second = start_attempt(self.user, self.pattern)
        self.assertNotEqual(first.pk, second.pk)
        submit_attempt(self.user, second.pk)
        start_attempt(self.user, self.pattern)
        with self.assertRaisesMessage(ValidationError, "Premium"):
            start_attempt(self.user, self.second_pattern)
        self.assertEqual(MockAttempt.objects.filter(user=self.user, mock_set=self.pattern.published_set).count(), 3)
        self.assertFalse(FreeMockSelection.objects.exists())
        self.assertEqual(MockAttempt.objects.count(), 3)

    def test_shared_exam_lock_in_both_directions(self):
        self.session(difficulty="hard")
        with self.assertRaisesMessage(ValidationError, "Free exam"):
            start_attempt(self.user, self.other_pattern)
        start_attempt(self.other_user, self.other_pattern)
        with self.assertRaisesMessage(ValidationError, "Free exam"):
            start_session(self.other_user, exam=self.exam, subject=self.subject, token=uuid4())

    def test_premium_all_exams_sets_and_no_free_consumption(self):
        self.premium()
        self.assertEqual(self.session().questions.count(), 51)
        start_session(self.user, exam=self.other_exam, subject=self.subject, token=uuid4())
        for pattern in (self.pattern, self.second_pattern, self.other_pattern):
            start_attempt(self.user, pattern)
        self.assertFalse(FreeExamSelection.objects.exists())
        self.assertFalse(FreeMockSelection.objects.exists())
        self.assertFalse(FreeQuestionUsage.objects.exists())

    def test_expiry_preserves_free_usage_and_premium_history(self):
        self.session(difficulty="easy", count="50")
        free_mock = start_attempt(self.user, self.pattern)
        submit_attempt(self.user, free_mock.pk)
        subscription = self.premium()
        premium_session = self.session(difficulty="hard")
        premium_mock = start_attempt(self.user, self.other_pattern)
        subscription.ends_at = timezone.now() - timedelta(seconds=1)
        subscription.save()
        with self.assertRaises(ValidationError):
            self.session(difficulty="hard")
        with self.assertRaises(ValidationError):
            start_attempt(self.user, self.second_pattern)
        self.assertEqual(start_attempt(self.user, self.other_pattern).pk, premium_mock.pk)
        self.assertEqual(start_session(self.user, exam=self.exam, subject=self.subject,
            token=premium_session.start_token, difficulty="hard").pk, premium_session.pk)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.session_url(premium_session)).status_code, 200)
        self.assertEqual(self.client.get(reverse("mock_tests:attempt_detail", args=[free_mock.pk]), follow=True).status_code, 200)
        self.assertEqual(FreeQuestionUsage.objects.count(), 50)

    def test_failed_assembly_rolls_back_all_allocations(self):
        with patch("practice.services.assemble_session", side_effect=ValidationError("failed")):
            with self.assertRaises(ValidationError):
                self.session()
        with patch("mock_tests.services.AttemptQuestion.save", side_effect=ValidationError("failed")):
            with self.assertRaises(ValidationError):
                start_attempt(self.user, self.pattern)
        self.assertFalse(FreeExamSelection.objects.exists())
        self.assertFalse(FreeMockSelection.objects.exists())
        self.assertFalse(FreeQuestionUsage.objects.exists())

    def test_guest_service_and_post_routes_cannot_allocate(self):
        with self.assertRaises(ValidationError):
            start_attempt(AnonymousUser(), self.pattern)
        with self.assertRaises(ValidationError):
            start_session(AnonymousUser(), exam=self.exam, subject=self.subject, token=uuid4())
        self.assertEqual(self.client.post(reverse("mock_tests:start", args=[self.pattern.pk])).status_code, 302)
        url = reverse("practice:difficulty", args=[self.authority.slug, self.exam.slug, self.subject.slug])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertFalse(FreeExamSelection.objects.exists())

    def test_upgrade_prompt_from_both_post_views(self):
        self.session(difficulty="easy", count="50")
        start_attempt(self.user, self.pattern)
        self.client.force_login(self.user)
        response = self.client.post(reverse("mock_tests:start", args=[self.second_pattern.pk]))
        self.assertContains(response, "upgrade to Premium", status_code=400)
        url = reverse("practice:difficulty", args=[self.authority.slug, self.exam.slug, self.subject.slug])
        response = self.client.post(url, {"difficulty": "level:hard", "token": uuid4(), "language": "en"})
        self.assertContains(response, "upgrade to Premium", status_code=400)

    def test_database_uniqueness_and_read_only_admin(self):
        self.session(difficulty="hard")
        with self.assertRaises(IntegrityError), transaction.atomic():
            FreeQuestionUsage.objects.create(user=self.user, question=self.hard)
        with self.assertRaises(IntegrityError), transaction.atomic():
            FreeExamSelection.objects.create(user=self.user, exam=self.other_exam)
        start_attempt(self.user, self.pattern)
        FreeMockSelection.objects.create(user=self.user, pattern=self.pattern)
        with self.assertRaises(IntegrityError), transaction.atomic():
            FreeMockSelection.objects.create(user=self.user, pattern=self.second_pattern)
        request = RequestFactory().get("/admin/")
        request.user = get_user_model().objects.create_superuser(username="allocation-admin", password=None)
        for model in (FreeExamSelection, FreeMockSelection, FreeQuestionUsage):
            model_admin = admin.site._registry[model]
            self.assertTrue(model_admin.has_view_permission(request))
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))

    def test_legacy_backfill_is_idempotent_and_excludes_premium_and_revision(self):
        # Simulate pre-B2 delivery without a ledger, using the unchanged assembler.
        with patch("billing.usage.practice_pool", side_effect=lambda user, exam, ids, **kw: (ids, False)):
            legacy = self.session(difficulty="easy")
        with patch("billing.usage.reserve_mock", return_value=False):
            start_attempt(self.user, self.pattern)
        from practice.services import assemble_session
        assemble_session(self.user, questions=[self.hard], configuration={"kind": "revision"}, token=uuid4(), kind="revision")
        subscription = self.premium()
        subscription.starts_at = timezone.now()
        subscription.save()
        self.session(difficulty="hard")
        executor = MigrationExecutor(connection)
        apps = executor.loader.project_state().apps
        migration = import_module("billing.migrations.0004_free_policy_and_legacy_usage")
        with connection.schema_editor() as editor:
            migration.configure_and_backfill(apps, editor)
            migration.configure_and_backfill(apps, editor)
        self.assertEqual(FreeQuestionUsage.objects.count(), 50)
        self.assertEqual(FreeExamSelection.objects.get(user=self.user).exam_id, legacy.exam_id)
        self.assertEqual(FreeMockSelection.objects.get(user=self.user).pattern_id, self.pattern.pk)


class ConcurrentFreeUsageTests(TransactionTestCase):
    def setUp(self):
        free_configuration()
        practice_tests.PracticeFixture.setUpTestData.__func__(type(self))
        practice_tests.PracticeFixture.question(self)
        practice_tests.PracticeFixture.question(self, exam=self.other_exam)
        self.pattern = make_pattern(self.exam, "Set one", free_demo=True)
        self.second_pattern = make_pattern(self.exam, "Set two")

    def race(self, functions):
        barrier = Barrier(2)
        def run(function):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    function()
                    return "allowed"
                except ValidationError:
                    return "blocked"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(run, functions))

    def test_two_mock_sets_cannot_both_be_selected(self):
        result = self.race([lambda: start_attempt(self.user, self.pattern),
                            lambda: start_attempt(self.user, self.second_pattern)])
        self.assertEqual(sorted(result), ["allowed", "blocked"])
        self.assertEqual(MockAttempt.objects.count(), 1)
        self.assertEqual(FreeMockSelection.objects.count(), 0)

    def test_different_exams_cannot_both_be_selected(self):
        result = self.race([lambda: start_attempt(self.user, self.pattern),
            lambda: start_session(self.user, exam=self.other_exam, subject=self.subject, token=uuid4())])
        self.assertEqual(sorted(result), ["allowed", "blocked"])
        self.assertEqual(FreeExamSelection.objects.count(), 1)

    def test_last_question_slot_cannot_be_spent_twice(self):
        # Two disjoint topic pools compete for the final remaining unit.
        from exams.models import Topic
        topic = Topic.objects.create(subject=self.subject, name="Another", slug="another")
        practice_tests.PracticeFixture.question(self, topic=topic)
        PlanEntitlement.objects.filter(plan__tier="free", feature="practice").update(usage_limit=1)
        result = self.race([
            lambda: start_session(self.user, exam=self.exam, subject=self.subject, topic=self.topic, token=uuid4()),
            lambda: start_session(self.user, exam=self.exam, subject=self.subject, topic=topic, token=uuid4()),
        ])
        self.assertEqual(sorted(result), ["allowed", "blocked"])
        self.assertEqual(FreeQuestionUsage.objects.count(), 1)
        self.assertEqual(PracticeSession.objects.count(), 1)
