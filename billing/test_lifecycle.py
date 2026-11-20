from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from importlib import import_module
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .lifecycle import (activate_subscription, expire_subscription, renew_subscription,
                        revoke_for_full_refund, revoke_subscription)
from .models import SubscriptionEvent, SubscriptionPlan, UserSubscription
from .services import plan_for, subscription_for
from practice import tests as practice_tests


class LifecycleFixture:
    def configure(self):
        self.user = get_user_model().objects.create_user(username="subscriber")
        self.actor = get_user_model().objects.create_user(username="billing-manager", is_staff=True)
        self.actor.user_permissions.add(Permission.objects.get(codename="manage_subscriptions"),
                                        Permission.objects.get(codename="grant_premium"),
                                        Permission.objects.get(codename="approve_refunds"),
                                        Permission.objects.get(codename="view_usersubscription"))
        self.plan, _ = SubscriptionPlan.objects.update_or_create(code="premium-30", defaults={
            "name": "Premium Monthly", "tier": "premium", "price": Decimal("149.00"),
            "currency": "INR", "duration_days": 30, "is_active": True})
        self.now = datetime(2026, 11, 16, 12, tzinfo=datetime_timezone.utc)

    def grant(self, **values):
        kwargs = dict(actor=self.actor, user=self.user, plan=self.plan,
                      event_key="activation", reason="Approved administrative grant", at=self.now)
        kwargs.update(values)
        return activate_subscription(**kwargs)

    def renew(self, **values):
        kwargs = dict(actor=self.actor, user=self.user, plan=self.plan,
                      event_key="renewal", reason="Approved renewal", at=self.now + timedelta(days=10))
        kwargs.update(values)
        return renew_subscription(**kwargs)


class SubscriptionLifecycleTests(LifecycleFixture, TestCase):
    def setUp(self):
        self.configure()

    def test_activation_and_snapshot(self):
        sub = self.grant()
        self.assertEqual(sub.starts_at, self.now)
        self.assertEqual(sub.ends_at, self.now + timedelta(days=30))
        self.assertEqual(subscription_for(self.user, at=self.now), sub)
        self.assertEqual(sub.plan_snapshot["price"], "149.00")
        self.assertEqual(sub.plan_snapshot["duration_days"], 30)
        event = sub.events.get()
        self.assertEqual(event.actor, self.actor)
        self.assertEqual(event.kind, "activation")
        self.assertEqual(event.reason, "Approved administrative grant")

    def test_monthly_quarterly_yearly_durations_are_plan_configuration(self):
        for duration in (30, 90, 365):
            self.plan.duration_days = duration
            self.plan.save()
            user = get_user_model().objects.create_user(username=f"duration-{duration}")
            sub = self.grant(user=user, event_key=f"duration-{duration}")
            self.assertEqual(sub.ends_at - sub.starts_at, timedelta(days=duration))

    def test_early_renewal_appends_term_without_changing_original(self):
        original = self.grant()
        self.plan.duration_days = 90
        self.plan.price = Decimal("399.00")
        self.plan.save()
        renewed = self.renew()
        self.assertEqual(renewed.starts_at, original.ends_at)
        self.assertEqual(renewed.ends_at, original.ends_at + timedelta(days=90))
        self.assertEqual(renewed.previous_subscription, original)
        self.assertEqual(subscription_for(self.user, at=original.ends_at), renewed)
        original.refresh_from_db()
        self.assertEqual(original.ends_at, self.now + timedelta(days=30))
        self.assertEqual(original.plan_snapshot["price"], "149.00")
        self.assertEqual(renewed.plan_snapshot["price"], "399.00")

    def test_multiple_early_renewals_extend_latest_expiry(self):
        original = self.grant()
        first = self.renew()
        second = self.renew(event_key="second-renewal")
        self.assertEqual(second.starts_at, first.ends_at)
        self.assertEqual(second.ends_at, original.ends_at + timedelta(days=60))

    def test_late_and_exact_expiry_renewal_start_new_term(self):
        original = self.grant()
        self.assertIsNone(subscription_for(self.user, at=original.ends_at))
        later = original.ends_at + timedelta(days=5)
        renewed = self.renew(at=later)
        self.assertEqual(renewed.starts_at, later)
        self.assertEqual(renewed.ends_at, later + timedelta(days=30))
        self.assertIsNone(renewed.previous_subscription)
        at_end = self.renew(at=renewed.ends_at, event_key="at-expiry")
        self.assertEqual(at_end.starts_at, renewed.ends_at)

    def test_expiry_falls_back_without_job_and_can_be_audited(self):
        original = self.grant()
        self.assertEqual(plan_for(self.user, at=original.ends_at).tier, "free")
        args = dict(actor=self.actor, subscription=original, event_key="expire", reason="Term elapsed", at=original.ends_at)
        expired = expire_subscription(**args)
        self.assertEqual(expired.status, "expired")
        self.assertEqual(expire_subscription(**args).pk, original.pk)
        self.assertEqual(SubscriptionEvent.objects.count(), 2)

    def test_expiration_rejects_unelapsed_term(self):
        original = self.grant()
        with self.assertRaises(ValidationError):
            expire_subscription(actor=self.actor, subscription=original, event_key="too-soon",
                                reason="Term elapsed", at=self.now)
        original.refresh_from_db()
        self.assertEqual(original.status, "active")

    def test_repeated_activation_and_renewal_are_idempotent(self):
        original = self.grant()
        self.assertEqual(self.grant().pk, original.pk)
        renewed = self.renew()
        self.assertEqual(self.renew().pk, renewed.pk)
        self.assertEqual(UserSubscription.objects.count(), 2)
        self.assertEqual(SubscriptionEvent.objects.count(), 2)
        with self.assertRaises(ValidationError):
            self.grant(event_key="another-activation")

    def test_event_key_conflicts_rejected_without_duplicate_access(self):
        self.grant()
        with self.assertRaises(ValidationError):
            self.grant(reason="Different grant")
        with self.assertRaises(ValidationError):
            self.renew(event_key="activation")
        other = get_user_model().objects.create_user(username="other-subscriber")
        with self.assertRaises(ValidationError):
            self.grant(user=other)
        self.assertEqual(UserSubscription.objects.count(), 1)

    def test_no_explicit_time_retries_do_not_extend_terms(self):
        with patch("billing.lifecycle.timezone.now", return_value=self.now):
            original = self.grant(at=None)
        with patch("billing.lifecycle.timezone.now", return_value=self.now + timedelta(days=1)):
            self.assertEqual(self.grant(at=None).pk, original.pk)
        self.assertEqual(UserSubscription.objects.count(), 1)

    def test_revocation_and_full_refund_preserve_history(self):
        original = self.grant()
        refund = dict(actor=self.actor, subscription=original, refund_reference="approved-refund-1",
                      event_key="refund-1", reason="Full refund approved", at=self.now + timedelta(days=5))
        self.assertEqual(revoke_for_full_refund(**refund).status, "revoked")
        self.assertIsNone(subscription_for(self.user, at=self.now + timedelta(days=6)))
        self.assertEqual(revoke_for_full_refund(**refund).pk, original.pk)
        original.refresh_from_db()
        self.assertEqual(original.ends_at, self.now + timedelta(days=30))
        self.assertEqual(original.plan_snapshot["price"], "149.00")
        self.assertEqual(original.events.count(), 2)
        with self.assertRaises(ValidationError):
            original.delete()

    def test_refund_of_future_renewal_does_not_revoke_original_term(self):
        original = self.grant()
        future = self.renew()
        revoke_for_full_refund(actor=self.actor, subscription=future, refund_reference="renewal-refund",
            event_key="renewal-refund", reason="Approved full refund", at=self.now + timedelta(days=11))
        self.assertEqual(subscription_for(self.user, at=self.now + timedelta(days=12)), original)
        self.assertIsNone(subscription_for(self.user, at=original.ends_at))

    def test_revoke_is_idempotent_and_cannot_be_undone_by_expiration(self):
        original = self.grant()
        args = dict(actor=self.actor, subscription=original, event_key="revoke", reason="Administrative revocation", at=self.now)
        revoke_subscription(**args)
        revoke_subscription(**args)
        expired = expire_subscription(actor=self.actor, subscription=original, event_key="expire-revoked",
                                      reason="Term elapsed", at=original.ends_at)
        self.assertEqual(expired.status, "revoked")
        self.assertEqual(original.events.count(), 3)

    def test_snapshots_and_audit_events_reject_mutation(self):
        sub = self.grant()
        sub.ends_at += timedelta(days=1)
        with self.assertRaises(ValidationError):
            sub.save()
        with self.assertRaises(ValidationError):
            UserSubscription.objects.filter(pk=sub.pk).update(status="cancelled")
        with self.assertRaises(ValidationError):
            UserSubscription.objects.all().delete()
        event = SubscriptionEvent.objects.get()
        event.reason = "Changed"
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            SubscriptionEvent.objects.all().update(reason="Changed")
        with self.assertRaises(ValidationError):
            event.delete()

    def test_inactive_sales_plan_does_not_revoke_managed_entitlement(self):
        sub = self.grant()
        self.plan.is_active = False
        self.plan.price = Decimal("999.00")
        self.plan.save()
        self.assertEqual(subscription_for(self.user, at=self.now), sub)
        sub.refresh_from_db()
        self.assertEqual(sub.plan_snapshot["price"], "149.00")
        with self.assertRaises(ValidationError):
            self.renew()

    def test_permission_account_audit_and_timezone_guards(self):
        for actor in (AnonymousUser(), self.user,
                      get_user_model().objects.create_user(username="unprivileged-staff", is_staff=True)):
            with self.assertRaises(PermissionDenied):
                self.grant(actor=actor)
        for fields in ({"reason": ""}, {"event_key": ""}, {"at": datetime(2026, 11, 16)}):
            with self.assertRaises(ValidationError):
                self.grant(**fields)
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(ValidationError):
            self.grant()
        self.assertFalse(UserSubscription.objects.exists())

    def test_audit_failure_rolls_back_grant(self):
        with patch("billing.lifecycle.SubscriptionEvent.save", side_effect=ValidationError("audit failure")):
            with self.assertRaises(ValidationError):
                self.grant()
        self.assertFalse(UserSubscription.objects.exists())

    def test_legacy_migration_snapshot_is_marked_inferred(self):
        sub = UserSubscription.objects.create(user=self.user, plan=self.plan, starts_at=self.now,
                                              ends_at=self.now + timedelta(days=30))
        apps = MigrationExecutor(connection).loader.project_state().apps
        with connection.schema_editor() as editor:
            import_module("billing.migrations.0006_snapshot_legacy_subscriptions").snapshot_legacy(apps, editor)
        sub.refresh_from_db()
        self.assertEqual(sub.plan_snapshot["source"], "legacy_current_configuration")
        self.assertEqual(sub.plan_snapshot["price"], "149.00")
        self.assertFalse(sub.events.exists())

    def test_admin_grant_is_permission_gated_audited_and_idempotent(self):
        url = reverse("admin:billing_usersubscription_lifecycle")
        self.client.force_login(self.actor)
        token = str(uuid4())
        data = dict(operation="activate", user=self.user.pk, plan=self.plan.pk,
                    reason="Manual administrative grant", event_key=token)
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(UserSubscription.objects.count(), 1)
        self.assertEqual(SubscriptionEvent.objects.get().actor, self.actor)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.actor)
        self.assertEqual(protected.post(url, data).status_code, 403)
        staff = get_user_model().objects.create_user(username="view-only", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="view_usersubscription"))
        self.client.force_login(staff)
        self.assertEqual(self.client.get(url).status_code, 403)
        request = RequestFactory().get("/admin/")
        request.user = self.actor
        self.assertFalse(admin.site._registry[UserSubscription].has_add_permission(request))
        self.assertFalse(admin.site._registry[UserSubscription].has_change_permission(request))
        self.assertFalse(admin.site._registry[UserSubscription].has_delete_permission(request))


class ConcurrentLifecycleTests(LifecycleFixture, TransactionTestCase):
    def setUp(self):
        self.configure()

    def race(self, functions):
        barrier = Barrier(2)
        def run(function):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return function().pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(run, functions))

    def test_same_activation_key_allocates_one_term(self):
        result = self.race([self.grant, self.grant])
        self.assertEqual(result[0], result[1])
        self.assertEqual(UserSubscription.objects.count(), 1)
        self.assertEqual(SubscriptionEvent.objects.count(), 1)

    def test_same_renewal_key_extends_once(self):
        self.grant()
        result = self.race([self.renew, self.renew])
        self.assertEqual(result[0], result[1])
        self.assertEqual(UserSubscription.objects.count(), 2)

    def test_distinct_renewals_do_not_lose_an_extension(self):
        original = self.grant()
        self.race([self.renew, lambda: self.renew(event_key="another-renewal")])
        terms = list(UserSubscription.objects.order_by("starts_at"))
        self.assertEqual(terms[-1].ends_at, original.ends_at + timedelta(days=60))
        self.assertEqual(terms[-1].starts_at, terms[-2].ends_at)


class LifecycleLearningTests(LifecycleFixture, practice_tests.PracticeFixture):
    def setUp(self):
        self.configure()
        self.now = timezone.now()

    def test_expiry_and_refund_preserve_free_choices_and_all_learning_history(self):
        from .models import FreeExamSelection, FreeMockSelection, FreeQuestionUsage
        from .test_usage import make_pattern
        from mock_tests.execution import submit_attempt
        from mock_tests.services import start_attempt
        from practice.models import PracticeSession
        from practice.services import assemble_session, start_session, submit_answer
        from revision.models import SavedQuestion
        from revision.services import set_saved
        question = self.question()
        self.question(exam=self.other_exam)
        free_session = self.session()
        submit_answer(self.user, free_session.pk, free_session.questions.get().pk, "A")
        pattern = make_pattern(self.exam, "Original free set", free_demo=True)
        free_mock = start_attempt(self.user, pattern)
        submit_attempt(self.user, free_mock.pk)
        set_saved(self.user, question.pk, saved=True)
        saved = SavedQuestion.objects.get(user=self.user, question=question)
        revision = assemble_session(self.user, questions=[question], configuration={"kind": "revision"},
                                    token=uuid4(), kind="revision")
        ledgers = (list(FreeExamSelection.objects.values()), list(FreeMockSelection.objects.values()),
                   list(FreeQuestionUsage.objects.values()))
        subscription = self.grant()
        premium_session = start_session(self.user, exam=self.other_exam, subject=self.subject, token=uuid4())
        other_pattern = make_pattern(self.other_exam, "Premium other-exam set")
        premium_mock = start_attempt(self.user, other_pattern)
        expire_subscription(actor=self.actor, subscription=subscription, event_key="expired-learning",
                            reason="Term elapsed", at=subscription.ends_at)
        with self.assertRaises(ValidationError):
            start_session(self.user, exam=self.other_exam, subject=self.subject, token=uuid4())
        renewed = self.renew(at=timezone.now())
        revoke_for_full_refund(actor=self.actor, subscription=renewed, refund_reference="learning-refund",
            event_key="learning-refund", reason="Full refund approved")
        self.assertEqual(ledgers, (list(FreeExamSelection.objects.values()), list(FreeMockSelection.objects.values()),
                                  list(FreeQuestionUsage.objects.values())))
        self.assertEqual(PracticeSession.objects.get(pk=free_session.pk).status, "completed")
        self.assertTrue(SavedQuestion.objects.filter(pk=saved.pk).exists())
        self.assertTrue(PracticeSession.objects.filter(pk=revision.pk, kind="revision").exists())
        self.assertEqual(start_attempt(self.user, other_pattern).pk, premium_mock.pk)
        self.assertEqual(start_session(self.user, exam=self.other_exam, subject=self.subject,
            token=premium_session.start_token).pk, premium_session.pk)
        free_mock.refresh_from_db()
        self.assertEqual(free_mock.status, "submitted")
