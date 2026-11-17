"""B6 request-boundary, rollback, and bounded-query validation."""
import json
import logging
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from practice import tests as practice_tests
from . import test_payments as payment_tests
from .models import (FinancialAuditEvent, FreeExamSelection, FreeQuestionUsage, PaymentEvent,
                     PaymentOrder, PaymentTransaction, PlanEntitlement, Refund, SubscriptionEvent,
                     SubscriptionPlan, UserSubscription)
from .payments import replay_payment_event
from .providers import SimulatedProvider
from .services import practice_access
from .test_usage import difficulty_question
from .usage import practice_pool


class CraftedAllowanceTests(practice_tests.PracticeFixture):
    def test_crafted_practice_and_admin_requests_cannot_reset_or_transfer_usage(self):
        first = self.question()
        difficulty_question(self, "hard")
        PlanEntitlement.objects.filter(plan__tier="free", feature="practice").update(usage_limit=1)
        self.session(difficulty="")
        self.client.force_login(self.user)
        response = self.client.post(reverse("practice:difficulty", args=[
            self.authority.slug, self.exam.slug, self.subject.slug]), {
            "difficulty": "level:hard", "language": "en", "token": uuid4(),
            "user_id": self.other_user.pk, "used": 0, "usage_limit": 999999,
            "plan": "premium", "exam": self.other_exam.pk, "question_ids": first.pk,
        })
        self.assertEqual(response.status_code, 400)
        usage = FreeQuestionUsage.objects.get(user=self.user)
        self.assertEqual(usage.question_id, first.pk)
        self.assertFalse(FreeQuestionUsage.objects.filter(user=self.other_user).exists())
        self.assertEqual(FreeExamSelection.objects.get(user=self.user).exam_id, self.exam.pk)
        for url in (reverse("admin:billing_freequestionusage_change", args=[usage.pk]),
                    reverse("admin:billing_usersubscription_add"),
                    reverse("admin:billing_usersubscription_lifecycle")):
            self.assertEqual(self.client.post(url, {"user": self.user.pk, "status": "active", "used": 0}).status_code, 302)
        self.assertEqual(FreeQuestionUsage.objects.count(), 1)
        self.assertFalse(UserSubscription.objects.exists())

    def test_locked_owner_recheck_denies_stale_active_account(self):
        self.question()
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertTrue(self.user.is_active)  # stale service caller, not browser data
        with self.assertRaises(ValidationError):
            self.session()
        self.assertFalse(FreeQuestionUsage.objects.exists())
        self.assertFalse(FreeExamSelection.objects.exists())


class EntitlementQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="query-student")

    def test_free_lookup_uses_three_queries(self):
        with self.assertNumQueries(3):
            self.assertTrue(practice_access(self.user).allowed)

    def test_premium_lookup_uses_two_queries_with_many_historical_terms(self):
        plan = SubscriptionPlan.objects.get(code="premium-30")
        plan.is_active = True
        plan.save()
        now = timezone.now()
        for offset in range(30):
            start = now - timedelta(days=31 * (offset + 1))
            UserSubscription.objects.create(user=self.user, plan=plan, starts_at=start, ends_at=start + timedelta(days=30))
        UserSubscription.objects.create(user=self.user, plan=plan, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=29))
        with self.assertNumQueries(2):
            self.assertTrue(practice_access(self.user).allowed)


class UsageQueryTests(practice_tests.PracticeFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.used = [cls.question(cls) for _ in range(30)]
        FreeQuestionUsage.objects.bulk_create([FreeQuestionUsage(user=cls.user, question=question) for question in cls.used])
        FreeExamSelection.objects.create(user=cls.user, exam=cls.exam)

    def test_membership_query_fetches_only_candidate_ids_and_counts_lifetime_in_sql(self):
        from random import Random
        candidates = {self.used[0].pk, self.used[1].pk}
        with CaptureQueriesContext(connection) as captured:
            pool, free = practice_pool(self.user, self.exam.pk, candidates, sampler=Random(1))
        self.assertTrue(free)
        self.assertEqual(pool, candidates)
        reads = [row["sql"] for row in captured.captured_queries if 'FROM "billing_freequestionusage"' in row["sql"]]
        self.assertEqual(len(reads), 2)
        self.assertTrue(any("COUNT(" in sql for sql in reads))
        self.assertTrue(any('"question_id" IN' in sql for sql in reads))
        self.assertEqual(len(captured), 9)  # six policy/usage SELECTs plus owner SELECT and savepoint pair


@override_settings(BILLING_SIMULATION_ENABLED=True, DEBUG=True, IS_PRODUCTION=False, DJANGO_ENV="dev")
class PaymentBoundaryTests(payment_tests.PaymentFixture, TestCase):
    def setUp(self):
        self.configure()

    def test_failure_after_subscription_write_rolls_back_every_financial_change(self):
        order = self.order()
        with patch("billing.audit.append_audit", side_effect=ValidationError("Audit unavailable")):
            with self.assertRaises(ValidationError):
                self.simulate(order)
        order.refresh_from_db()
        self.assertEqual(order.status, "created")
        self.assertEqual(PaymentEvent.objects.get().result, "received")
        self.assertFalse(UserSubscription.objects.exists())
        self.assertFalse(SubscriptionEvent.objects.exists())
        self.assertFalse(PaymentTransaction.objects.exists())
        self.assertEqual(replay_payment_event(actor=self.actor, order=order).status, "paid")
        self.assertEqual(UserSubscription.objects.count(), 1)

    def test_failure_after_refund_revocation_is_atomic_and_retryable(self):
        order = self.simulate(self.order())
        from .finance import approve_refund
        approve_refund(actor=self.actor, order=order, reason="Approved refund for rollback validation", event_key="rollback-approval")
        with patch("billing.audit.append_audit", side_effect=ValidationError("Audit unavailable")):
            with self.assertRaises(ValidationError):
                self.simulate(order, "full_refund", "refund-audit-failure")
        order.refresh_from_db()
        order.subscription.refresh_from_db()
        self.assertEqual(order.status, "paid")
        self.assertEqual(order.subscription.status, "active")
        self.assertFalse(Refund.objects.exists())
        self.assertEqual(PaymentEvent.objects.get(outcome="full_refund").result, "received")
        self.assertEqual(SubscriptionEvent.objects.count(), 1)
        self.assertEqual(replay_payment_event(actor=self.actor, order=order).status, "refunded")

    def test_nonfinite_provider_amounts_are_rejected_without_side_effects(self):
        order = self.order()
        event = SimulatedProvider().record_event(actor=self.actor, order=order, outcome="success", event_key="invalid-amount")
        verified = SimulatedProvider().verify_event(event.reference)
        for amount in ("NaN", "sNaN", "Infinity", "-Infinity"):
            with patch("billing.providers.SimulatedProvider.verify_event", return_value=replace(verified, amount=amount)):
                with self.assertRaises(ValidationError):
                    replay_payment_event(actor=self.actor, order=order)
        self.assertFalse(UserSubscription.objects.exists())
        self.assertFalse(PaymentTransaction.objects.exists())
        self.assertEqual(PaymentEvent.objects.get().result, "received")

    def test_ignored_browser_payment_fields_are_not_stored_or_logged(self):
        self.client.force_login(self.user)
        marker = "synthetic-sensitive-field-do-not-retain"
        captured = []
        class Capture(logging.Handler):
            def emit(self, record):
                captured.append(record.getMessage())
        handler = Capture()
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            response = self.client.post(reverse("billing:checkout", args=[self.plan.pk]), {
                "checkout_key": uuid4(), "status": "success", "is_premium": True,
                "card_number": marker, "cvv": marker, "gateway_secret": marker,
            })
        finally:
            root.removeHandler(handler)
        self.assertEqual(response.status_code, 302)
        order = PaymentOrder.objects.get()
        self.assertEqual(order.status, "created")
        self.assertNotIn(marker, json.dumps(order.plan_snapshot))
        self.assertNotIn(marker, "\n".join(captured))
        self.assertFalse(UserSubscription.objects.exists())
        self.assertFalse(PaymentEvent.objects.exists())
        self.assertFalse(FinancialAuditEvent.objects.exists())
