from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from billing.models import FreeExamSelection, FreeQuestionUsage, PlanEntitlement, SubscriptionPlan, UserSubscription
from billing.test_usage import difficulty_question, free_configuration
from questions.services import create_revision, mark_reviewed, publish_question
from revision.models import SavedQuestion
from revision.services import set_saved
from . import tests as practice_tests
from .models import PracticeSession
from .services import start_session


class IncrementalAllocationTests(practice_tests.PracticeFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.easy = [difficulty_question(cls, "easy") for _ in range(10)]
        cls.hard = [difficulty_question(cls, "hard") for _ in range(41)]

    def ids(self, session):
        return set(session.questions.values_list("question_id", flat=True))

    def test_registration_has_no_allocations_and_first_session_reserves_ten_before_assembly(self):
        fresh = get_user_model().objects.create_user(username="unallocated-account")
        self.assertFalse(FreeQuestionUsage.objects.filter(user=fresh).exists())
        self.assertFalse(FreeExamSelection.objects.filter(user=fresh).exists())
        from .services import assemble_session
        def observed_assembly(user, **kwargs):
            self.assertEqual(FreeQuestionUsage.objects.filter(user=user).count(), 10)
            self.assertEqual(set(FreeQuestionUsage.objects.filter(user=user).values_list("question_id", flat=True)),
                             {question.pk for question in kwargs["questions"]})
            return assemble_session(user, **kwargs)
        with patch("practice.services.assemble_session", side_effect=observed_assembly):
            session = start_session(fresh, exam=self.exam, subject=self.subject, token=uuid4())
        self.assertEqual(session.questions.count(), 10)
        self.assertTrue(all(usage.delivered_at <= session.started_at for usage in FreeQuestionUsage.objects.filter(user=fresh)))

    def test_five_distinct_default_batches_reach_fifty_and_next_new_batch_is_blocked(self):
        delivered = set()
        for count in range(1, 6):
            session = self.session()
            batch = self.ids(session)
            self.assertEqual(len(batch), 10)
            self.assertFalse(delivered & batch)
            delivered |= batch
            self.assertEqual(FreeQuestionUsage.objects.filter(user=self.user).count(), 10 * count)
        with self.assertRaisesMessage(ValidationError, "upgrade to Premium"):
            self.session()
        self.assertEqual(len(delivered), 50)
        self.assertEqual(PracticeSession.objects.count(), 5)

    def test_configurable_quota_has_a_partial_final_batch(self):
        PlanEntitlement.objects.filter(plan__tier="free", feature="practice").update(usage_limit=13)
        self.assertEqual(self.session().questions.count(), 10)
        self.assertEqual(self.session().questions.count(), 3)
        self.assertEqual(FreeQuestionUsage.objects.count(), 13)
        with self.assertRaises(ValidationError):
            self.session()

    @override_settings(PRACTICE_FREE_SESSION_SIZE=4)
    def test_default_batch_size_is_configurable(self):
        first = self.session()
        second = self.session()
        self.assertEqual(first.questions.count(), 4)
        self.assertEqual(second.questions.count(), 4)
        self.assertFalse(self.ids(first) & self.ids(second))
        self.assertEqual(FreeQuestionUsage.objects.count(), 8)

    def test_existing_explicit_count_options_still_work(self):
        self.assertEqual(self.session(count="20").questions.count(), 20)
        self.assertEqual(self.session().questions.count(), 10)
        self.assertEqual(FreeQuestionUsage.objects.count(), 30)

    def test_revisits_and_new_revisions_do_not_consume_slots(self):
        first = self.session(difficulty="easy")
        chosen = self.easy[0]
        original_revision = first.questions.get(question=chosen).question_revision_id
        create_revision(chosen, language="en", question_text="New Practice edition", option_a="A",
                        option_b="B", option_c="C", option_d="D", correct_answer="A")
        publish_question(mark_reviewed(chosen))
        repeat = self.session(difficulty="easy")
        self.assertEqual(self.ids(first), self.ids(repeat))
        self.assertEqual(FreeQuestionUsage.objects.count(), 10)
        self.assertNotEqual(repeat.questions.get(question=chosen).question_revision_id, original_revision)
        self.assertEqual(first.questions.get(question=chosen).question_revision_id, original_revision)
        self.assertEqual(self.session(token=first.start_token, difficulty="easy").pk, first.pk)

    def test_exhausted_user_can_revisit_allocated_scope_but_cannot_allocate_another(self):
        PlanEntitlement.objects.filter(plan__tier="free", feature="practice").update(usage_limit=10)
        first = self.session(difficulty="easy")
        repeat = self.session(difficulty="easy")
        self.assertEqual(self.ids(first), self.ids(repeat))
        with self.assertRaisesMessage(ValidationError, "upgrade to Premium"):
            self.session(difficulty="hard")
        self.assertEqual(FreeQuestionUsage.objects.count(), 10)

    def test_failed_assembly_rolls_back_selection_and_reserved_slots(self):
        with patch("practice.services.assemble_session", side_effect=ValidationError("Assembly failed")):
            with self.assertRaises(ValidationError):
                self.session()
        self.assertFalse(FreeQuestionUsage.objects.exists())
        self.assertFalse(FreeExamSelection.objects.exists())
        self.assertFalse(PracticeSession.objects.exists())

    def test_browser_default_and_duplicate_post_are_incremental(self):
        self.client.force_login(self.user)
        url = reverse("practice:difficulty", args=[self.authority.slug, self.exam.slug, self.subject.slug])
        payload = {"difficulty": "level:hard", "token": uuid4(), "language": "en", "count": "50", "used": 0}
        first = self.client.post(url, payload)
        second = self.client.post(url, payload)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(first.url, second.url)
        self.assertEqual(PracticeSession.objects.get().questions.count(), 10)
        self.assertEqual(FreeQuestionUsage.objects.count(), 10)

    def test_premium_expiry_restores_original_exam_and_remaining_allowance(self):
        first = self.session()
        original_ids = self.ids(first)
        saved_question = first.questions.first().question
        set_saved(self.user, saved_question.pk, saved=True)
        bookmark = SavedQuestion.objects.get(user=self.user, question=saved_question)
        plan = SubscriptionPlan.objects.get(code="premium-30")
        plan.is_active = True
        plan.save()
        subscription = UserSubscription.objects.create(user=self.user, plan=plan,
            starts_at=timezone.now() - timedelta(days=1), ends_at=timezone.now() + timedelta(days=29))
        premium_session = self.session()
        self.assertEqual(premium_session.questions.count(), 51)
        self.question(exam=self.other_exam)
        other = start_session(self.user, exam=self.other_exam, subject=self.subject, token=uuid4())
        self.assertEqual(FreeQuestionUsage.objects.count(), 10)
        subscription.ends_at = timezone.now() - timedelta(seconds=1)
        subscription.save()
        next_free = self.session()
        self.assertEqual(next_free.questions.count(), 10)
        self.assertFalse(self.ids(next_free) & original_ids)
        self.assertEqual(FreeQuestionUsage.objects.count(), 20)
        self.assertEqual(FreeExamSelection.objects.get(user=self.user).exam, self.exam)
        with self.assertRaisesMessage(ValidationError, "Free exam"):
            start_session(self.user, exam=self.other_exam, subject=self.subject, token=uuid4())
        self.assertEqual(start_session(self.user, exam=self.other_exam, subject=self.subject, token=other.start_token).pk, other.pk)
        self.assertEqual(self.session(token=first.start_token).pk, first.pk)
        self.assertEqual(self.ids(first), original_ids)
        self.assertTrue(SavedQuestion.objects.filter(pk=bookmark.pk).exists())
        self.assertEqual(premium_session.questions.count(), 51)


class ConcurrentIncrementalTests(TransactionTestCase):
    def setUp(self):
        free_configuration()
        practice_tests.PracticeFixture.setUpTestData.__func__(type(self))
        self.pool = [practice_tests.PracticeFixture.question(self) for _ in range(51)]

    def race(self, tokens):
        barrier = Barrier(2)
        def start(token):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    return start_session(self.user, exam=self.exam, subject=self.subject, token=token).pk
                except ValidationError:
                    return None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(start, tokens))

    def test_two_devices_receive_disjoint_incremental_batches(self):
        sessions = self.race([uuid4(), uuid4()])
        self.assertNotIn(None, sessions)
        batches = [set(PracticeSession.objects.get(pk=pk).questions.values_list("question_id", flat=True)) for pk in sessions]
        self.assertEqual([len(batch) for batch in batches], [10, 10])
        self.assertFalse(batches[0] & batches[1])
        self.assertEqual(FreeQuestionUsage.objects.count(), 20)

    def test_concurrent_same_token_returns_one_batch(self):
        token = uuid4()
        sessions = self.race([token, token])
        self.assertEqual(sessions[0], sessions[1])
        self.assertEqual(PracticeSession.objects.count(), 1)
        self.assertEqual(FreeQuestionUsage.objects.count(), 10)

    def test_last_ten_slots_cannot_be_spent_twice(self):
        FreeExamSelection.objects.create(user=self.user, exam=self.exam)
        FreeQuestionUsage.objects.bulk_create([FreeQuestionUsage(user=self.user, question=question) for question in self.pool[:40]])
        sessions = self.race([uuid4(), uuid4()])
        self.assertEqual(sessions.count(None), 1)
        self.assertEqual(FreeQuestionUsage.objects.count(), 50)
        self.assertEqual(PracticeSession.objects.get().questions.count(), 10)
