from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4
import runpy

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.conf import settings
from django.db import close_old_connections
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (PaymentEvent, PaymentOrder, PaymentTransaction, Refund,
                     SubscriptionEvent, SubscriptionPlan, UserSubscription)
from .payments import create_order, process_payment_event, replay_payment_event, simulate_payment
from .providers import SimulatedProvider, simulation_enabled
from .services import subscription_for


class PaymentFixture:
    def configure(self):
        self.user = get_user_model().objects.create_user(username="checkout-student")
        self.other = get_user_model().objects.create_user(username="other-student")
        self.actor = get_user_model().objects.create_user(username="checkout-operator", is_staff=True)
        self.actor.user_permissions.add(Permission.objects.get(codename="manage_subscriptions"),
                                        Permission.objects.get(codename="approve_refunds"),
                                        Permission.objects.get(codename="run_simulated_payments"))
        self.plan, _ = SubscriptionPlan.objects.update_or_create(code="premium-30", defaults={
            "name": "Premium Monthly", "tier": "premium", "price": Decimal("149.00"),
            "currency": "INR", "duration_days": 30, "is_active": True})

    def order(self, **values):
        kwargs = dict(user=self.user, plan=self.plan, checkout_key=uuid4())
        kwargs.update(values)
        return create_order(**kwargs)

    def simulate(self, order, outcome="success", key="payment-event"):
        return simulate_payment(actor=self.actor, order=order, outcome=outcome, event_key=key)


@override_settings(BILLING_SIMULATION_ENABLED=True, DEBUG=True, IS_PRODUCTION=False, DJANGO_ENV="dev")
class PaymentTests(PaymentFixture, TestCase):
    def setUp(self):
        self.configure()

    def test_checkout_freezes_quote_and_is_idempotent(self):
        key = uuid4()
        order = self.order(checkout_key=key)
        self.plan.price = Decimal("499.00")
        self.plan.save()
        self.assertEqual(self.order(checkout_key=key).pk, order.pk)
        self.assertEqual(order.amount, Decimal("149.00"))
        self.assertEqual(order.plan_snapshot["price"], "149.00")
        self.assertEqual(PaymentOrder.objects.count(), 1)
        self.assertFalse(UserSubscription.objects.exists())

    def test_success_activates_and_preserves_quote_after_plan_edit(self):
        order = self.order()
        self.plan.price = Decimal("399.00")
        self.plan.duration_days = 90
        self.plan.is_active = False
        self.plan.save()
        paid = self.simulate(order)
        self.assertEqual(paid.status, "paid")
        self.assertEqual(paid.subscription.ends_at - paid.subscription.starts_at, timedelta(days=30))
        self.assertEqual(paid.subscription.plan_snapshot["price"], "149.00")
        self.assertEqual(subscription_for(self.user), paid.subscription)
        self.assertEqual(PaymentTransaction.objects.get().status, "success")
        self.assertEqual(PaymentEvent.objects.get().result, "processed")

    def test_pending_then_success_uses_one_transaction_and_one_term(self):
        order = self.order()
        self.assertEqual(self.simulate(order, "pending", "pending").status, "pending")
        self.assertFalse(UserSubscription.objects.exists())
        self.assertEqual(self.simulate(order, "success", "confirmed").status, "paid")
        self.assertEqual(PaymentTransaction.objects.count(), 1)
        self.assertEqual(PaymentEvent.objects.count(), 2)
        self.assertEqual(UserSubscription.objects.count(), 1)

    def test_failed_payment_never_activates_and_late_success_is_ignored(self):
        order = self.order()
        self.assertEqual(self.simulate(order, "failed", "failed").status, "failed")
        self.assertEqual(self.simulate(order, "success", "late-success").status, "failed")
        self.assertFalse(UserSubscription.objects.exists())
        self.assertEqual(PaymentTransaction.objects.get().status, "failed")
        self.assertEqual(PaymentEvent.objects.get(reference="sim-event:late-success").result, "ignored")

    def test_duplicate_same_and_distinct_event_ids_cannot_activate_twice(self):
        order = self.order()
        paid = self.simulate(order)
        self.assertEqual(self.simulate(order).subscription_id, paid.subscription_id)
        self.assertEqual(replay_payment_event(actor=self.actor, order=order).subscription_id, paid.subscription_id)
        self.assertEqual(self.simulate(order, "success", "another-success").subscription_id, paid.subscription_id)
        self.assertEqual(UserSubscription.objects.count(), 1)
        self.assertEqual(SubscriptionEvent.objects.count(), 1)
        self.assertEqual(PaymentTransaction.objects.count(), 1)
        self.assertEqual(PaymentEvent.objects.count(), 2)

    def test_second_paid_order_renews_from_existing_expiry(self):
        first = self.simulate(self.order())
        second = self.simulate(self.order(), key="second-order")
        self.assertEqual(second.subscription.starts_at, first.subscription.ends_at)
        self.assertEqual(second.subscription.ends_at, first.subscription.ends_at + timedelta(days=30))

    def test_full_refund_is_auditable_revokes_and_is_idempotent(self):
        order = self.order()
        paid = self.simulate(order)
        self.assertEqual(self.simulate(order, "full_refund", "refund").status, "refunded")
        self.simulate(order, "full_refund", "refund")
        self.simulate(order, "full_refund", "duplicate-refund")
        self.simulate(order, "success", "success-after-refund")
        paid.subscription.refresh_from_db()
        self.assertEqual(paid.subscription.status, "revoked")
        self.assertIsNone(subscription_for(self.user))
        self.assertEqual(Refund.objects.count(), 1)
        self.assertEqual(Refund.objects.get().amount, order.amount)
        self.assertEqual(SubscriptionEvent.objects.count(), 2)
        self.assertEqual(PaymentTransaction.objects.get().status, "success")

    def test_unpaid_refund_rejected_and_receipt_retained(self):
        order = self.order()
        with self.assertRaises(ValidationError):
            self.simulate(order, "full_refund", "unpaid-refund")
        self.assertFalse(Refund.objects.exists())
        self.assertFalse(PaymentEvent.objects.exists())
        self.assertFalse(UserSubscription.objects.exists())

    def test_refund_failure_is_atomic_and_retryable(self):
        order = self.simulate(self.order())
        with patch("billing.payments.revoke_for_full_refund", side_effect=ValidationError("revocation unavailable")):
            with self.assertRaises(ValidationError):
                self.simulate(order, "full_refund", "retry-refund")
        order.refresh_from_db()
        self.assertEqual(order.status, "paid")
        self.assertFalse(Refund.objects.exists())
        self.assertIsNotNone(subscription_for(self.user))
        self.assertEqual(replay_payment_event(actor=self.actor, order=order).status, "refunded")
        self.assertIsNone(subscription_for(self.user))

    def test_mismatched_provider_amount_cannot_activate(self):
        order = self.order()
        event = SimulatedProvider().record_event(actor=self.actor, order=order, outcome="success", event_key="mismatch")
        verified = SimulatedProvider().verify_event(event.reference)
        for changes in ({"amount": "1.00"}, {"currency": "USD"}, {"order_reference": "wrong-order"},
                        {"transaction_reference": "wrong-payment"}, {"outcome": "failed"}):
            with patch("billing.providers.SimulatedProvider.verify_event", return_value=replace(verified, **changes)):
                with self.assertRaises(ValidationError):
                    process_payment_event(actor=self.actor, event_reference=event.reference)
        self.assertFalse(UserSubscription.objects.exists())
        self.assertFalse(PaymentTransaction.objects.exists())

    def test_fulfillment_failure_rolls_back_ledger_changes_but_keeps_receipt(self):
        order = self.order()
        with patch("billing.payments._fulfill_paid_order", side_effect=ValidationError("grant unavailable")):
            with self.assertRaises(ValidationError):
                self.simulate(order)
        order.refresh_from_db()
        self.assertEqual(order.status, "created")
        self.assertEqual(PaymentEvent.objects.get().result, "received")
        self.assertFalse(PaymentTransaction.objects.exists())
        self.assertEqual(replay_payment_event(actor=self.actor, order=order).status, "paid")

    def test_cross_order_event_key_reuse_rejected(self):
        self.simulate(self.order())
        with self.assertRaises(ValidationError):
            self.simulate(self.order(user=self.other))
        self.assertEqual(UserSubscription.objects.count(), 1)

    def test_ledger_reference_mutation_and_deletion_rejected(self):
        order = self.simulate(self.order())
        self.simulate(order, "full_refund", "refund")
        for record in (order, PaymentTransaction.objects.get(), PaymentEvent.objects.first(), Refund.objects.get()):
            with self.assertRaises(ValidationError):
                record.delete()
            with self.assertRaises(ValidationError):
                type(record).objects.all().delete()
            with self.assertRaises(ValidationError):
                type(record).objects.all().update(currency="USD")
        order.provider_reference = "different-order-reference"
        with self.assertRaises(ValidationError):
            order.save(_financial=True)

    def test_browser_status_parameters_cannot_activate_or_confirm(self):
        order = self.order()
        self.client.force_login(self.user)
        status_url = reverse("billing:status", args=[order.reference])
        self.assertEqual(self.client.get(status_url + "?status=success&paid=true").status_code, 200)
        self.assertEqual(self.client.post(status_url, {"status": "success"}).status_code, 405)
        self.assertEqual(self.client.get(reverse("billing:confirmation", args=[order.reference]) + "?status=success").status_code, 302)
        self.assertFalse(UserSubscription.objects.exists())

    def test_pricing_checkout_status_confirmation_and_owner_scope(self):
        self.assertContains(self.client.get(reverse("billing:pricing")), "Premium Monthly")
        self.client.force_login(self.user)
        data = {"checkout_key": uuid4(), "amount": "0", "status": "success"}
        response = self.client.post(reverse("billing:checkout", args=[self.plan.pk]), data)
        order = PaymentOrder.objects.get()
        self.assertRedirects(response, reverse("billing:status", args=[order.reference]))
        self.assertEqual(order.amount, Decimal("149.00"))
        self.assertNotContains(self.client.get(response.url), "Authorized test controls")
        self.simulate(order)
        confirmation = reverse("billing:confirmation", args=[order.reference])
        self.assertContains(self.client.get(confirmation), "Premium subscription confirmed")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(response.url).status_code, 404)
        self.assertEqual(self.client.get(confirmation).status_code, 404)

    def test_simulation_requires_explicit_configuration_and_both_permissions(self):
        order = self.order()
        for actor in (self.user, get_user_model().objects.create_user(username="staff-only", is_staff=True)):
            with self.assertRaises(PermissionDenied):
                simulate_payment(actor=actor, order=order, outcome="success", event_key="forbidden")
        with override_settings(BILLING_SIMULATION_ENABLED=False):
            self.assertFalse(simulation_enabled())
            with self.assertRaises(PermissionDenied):
                self.simulate(order)
            with self.assertRaises(PermissionDenied):
                self.order()
        for overrides in ({"IS_PRODUCTION": True}, {"DJANGO_ENV": "prod"}, {"DEBUG": False}):
            with override_settings(**overrides):
                self.assertFalse(simulation_enabled())
                with self.assertRaises(PermissionDenied):
                    self.simulate(order)
        self.assertFalse(UserSubscription.objects.exists())

    def test_production_configuration_fails_at_settings_load(self):
        environment = {"DJANGO_ENV": "prod", "DJANGO_DEBUG": "False", "BILLING_SIMULATION_ENABLED": "True",
            "DJANGO_SECRET_KEY": "settings-test-only-placeholder", "DJANGO_ALLOWED_HOSTS": "example.test",
            "DJANGO_SECURE_SSL_REDIRECT": "True", "DATABASE_NAME": "test_placeholder",
            "DATABASE_USER": "test_placeholder", "DATABASE_PASSWORD": "test-placeholder",
            "DATABASE_HOST": "localhost"}
        with patch.dict("os.environ", environment):
            with self.assertRaisesMessage(ImproperlyConfigured, "Billing simulation requires"):
                runpy.run_path(str(settings.BASE_DIR / "config" / "settings.py"))

    def test_production_pricing_and_checkout_fail_closed(self):
        self.client.force_login(self.user)
        with override_settings(IS_PRODUCTION=True, DJANGO_ENV="prod", DEBUG=False):
            response = self.client.get(reverse("billing:pricing"))
            self.assertContains(response, "Purchases are currently unavailable")
            self.assertNotContains(response, "Start test checkout")
            self.assertEqual(self.client.post(reverse("billing:checkout", args=[self.plan.pk]),
                {"checkout_key": uuid4()}).status_code, 403)
        self.assertFalse(PaymentOrder.objects.exists())

    def test_simulation_routes_csrf_guests_and_unauthorized_students(self):
        order = self.order()
        url = reverse("billing:simulate", args=[order.reference])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url, {"outcome": "success", "event_key": "student"}).status_code, 403)
        self.client.force_login(self.actor)
        self.assertEqual(self.client.get(url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        self.assertEqual(client.post(url, {"outcome": "success", "event_key": "csrf"}).status_code, 403)
        self.assertEqual(self.client.post(url, {"outcome": "pending", "event_key": "staff"}).status_code, 200)
        with override_settings(BILLING_SIMULATION_ENABLED=False):
            self.assertEqual(self.client.post(url).status_code, 404)

    def test_financial_admin_is_read_only_and_controls_are_permission_gated(self):
        order = self.order()
        superuser = get_user_model().objects.create_superuser(username="finance-admin", password=None)
        request = RequestFactory().get("/admin/")
        request.user = superuser
        for model in (PaymentOrder, PaymentTransaction, PaymentEvent, Refund):
            model_admin = admin.site._registry[model]
            self.assertTrue(model_admin.has_view_permission(request))
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
        self.client.force_login(superuser)
        url = reverse("admin:billing_paymentorder_change", args=[order.pk])
        self.assertContains(self.client.get(url), "Authorized test controls")
        with override_settings(DEBUG=False, IS_PRODUCTION=True):
            self.assertNotContains(self.client.get(url), "Authorized test controls")


@override_settings(BILLING_SIMULATION_ENABLED=True, DEBUG=True, IS_PRODUCTION=False, DJANGO_ENV="dev")
class ConcurrentPaymentTests(PaymentFixture, TransactionTestCase):
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

    def test_simultaneous_checkout_retries_create_one_order(self):
        key = uuid4()
        result = self.race([lambda: self.order(checkout_key=key), lambda: self.order(checkout_key=key)])
        self.assertEqual(result[0], result[1])
        self.assertEqual(PaymentOrder.objects.count(), 1)

    def test_simultaneous_duplicate_events_grant_once(self):
        order = self.order()
        self.race([lambda: self.simulate(order), lambda: self.simulate(order)])
        self.assertEqual(UserSubscription.objects.count(), 1)
        self.assertEqual(PaymentEvent.objects.count(), 1)
        self.assertEqual(PaymentTransaction.objects.count(), 1)

    def test_distinct_success_events_and_refund_events_remain_idempotent(self):
        order = self.order()
        self.race([lambda: self.simulate(order, key="success-one"), lambda: self.simulate(order, key="success-two")])
        self.assertEqual(UserSubscription.objects.count(), 1)
        self.race([lambda: self.simulate(order, "full_refund", "refund-one"),
                   lambda: self.simulate(order, "full_refund", "refund-two")])
        self.assertEqual(Refund.objects.count(), 1)
        self.assertEqual(SubscriptionEvent.objects.count(), 2)

    def test_same_event_key_cannot_confirm_two_accounts(self):
        first = self.order()
        second = self.order(user=self.other)
        barrier = Barrier(2)
        def confirm(order):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    self.simulate(order, key="cross-account-key")
                    return "paid"
                except ValidationError:
                    return "rejected"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(confirm, [first, second]))
        self.assertEqual(sorted(results), ["paid", "rejected"])
        self.assertEqual(PaymentEvent.objects.count(), 1)
        self.assertEqual(UserSubscription.objects.count(), 1)
