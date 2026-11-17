import csv
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, transaction, IntegrityError
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .accounting import (INDIA, financial_year, issue_document, retention_review, save_configuration, tax_totals)
from .exports import export_csv
from .finance import approve_refund, latest_reconciliation, record_reconciliation, record_settlement, save_plan_configuration
from .lifecycle import activate_subscription
from .models import (BillingConfiguration, BillingDocument, FinancialAuditEvent, PaymentOrder,
                     PaymentTransaction, ReconciliationRecord, Refund, RefundApproval, Settlement, SubscriptionPlan)
from .payments import create_order, simulate_payment
from .roles import configure_roles, ROLE_PERMISSIONS


class FinanceFixture:
    def configure(self):
        self.user = get_user_model().objects.create_user(username="finance-student")
        self.actor = get_user_model().objects.create_superuser(username="finance-operator", password=None)
        self.plan, _ = SubscriptionPlan.objects.update_or_create(code="premium-30", defaults={
            "name": "Premium Monthly", "tier": "premium", "price": Decimal("118.00"),
            "currency": "INR", "duration_days": 30, "is_active": True})

    def paid(self):
        order = create_order(user=self.user, plan=self.plan, checkout_key=uuid4())
        return simulate_payment(actor=self.actor, order=order, outcome="success", event_key=str(uuid4()))

    def config(self, **changes):
        values = dict(seller_name="Test Subscription Seller", seller_address="Test seller address, India",
                      tax_registered=False, tax_mode="none", tax_components=[])
        values.update(changes)
        return save_configuration(actor=self.actor, configuration=BillingConfiguration(**values),
                                  reason="Reviewed test configuration", reviewed=True)

    def document(self, order, **changes):
        return issue_document(actor=self.actor, order=order, reason="Issue accounting document", event_key=str(uuid4()), **changes)

    def staff(self, code):
        user = get_user_model().objects.create_user(username="staff-" + code, is_staff=True)
        user.user_permissions.add(Permission.objects.get(content_type__app_label="billing", codename=code))
        return user


@override_settings(BILLING_SIMULATION_ENABLED=True, DEBUG=True, IS_PRODUCTION=False, DJANGO_ENV="dev")
class FinanceTests(FinanceFixture, TestCase):
    def setUp(self):
        self.configure()

    def test_role_groups_are_idempotent_and_separate_authorities(self):
        configure_roles()
        configure_roles()
        self.assertEqual(Group.objects.filter(name__in=ROLE_PERMISSIONS).count(), 6)
        viewer = self.staff("view_financial_records")
        request = RequestFactory().get("/admin/")
        request.user = viewer
        for model in (PaymentOrder, PaymentTransaction, Refund, BillingDocument, FinancialAuditEvent, Settlement):
            model_admin = admin.site._registry[model]
            self.assertTrue(model_admin.has_view_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
        with self.assertRaises(PermissionDenied):
            activate_subscription(actor=viewer, user=self.user, plan=self.plan, event_key="viewer-grant", reason="Denied")
        with self.assertRaises(PermissionDenied):
            export_csv(actor=viewer, report="sales", reason="Denied")
        self.assertFalse(viewer.has_perm("billing.approve_refunds"))
        for group in Group.objects.filter(name__in=ROLE_PERMISSIONS):
            self.assertFalse(group.permissions.filter(codename="run_simulated_payments").exists())

    def test_manual_granter_does_not_need_payment_or_refund_permissions(self):
        granter = self.staff("grant_premium")
        subscription = activate_subscription(actor=granter, user=self.user, plan=self.plan, event_key="grant", reason="Manual grant approved")
        self.assertEqual(subscription.events.get().actor, granter)
        self.assertFalse(granter.has_perm("billing.approve_refunds"))
        operator = self.staff("manage_subscriptions")
        with self.assertRaises(PermissionDenied):
            activate_subscription(actor=operator, user=self.user, plan=self.plan, event_key="operator-grant", reason="Denied")

    def test_plan_edits_require_plan_role_and_append_before_after_audit(self):
        actor = self.staff("manage_plans")
        self.plan.price = Decimal("199.00")
        save_plan_configuration(actor=actor, instance=self.plan, reason="Reviewed price revision")
        event = FinancialAuditEvent.objects.get(action="plan_configuration_saved")
        self.assertEqual(event.actor, actor)
        self.assertEqual(event.before["price"], "118.00")
        self.assertEqual(event.after["price"], "199.00")
        request = RequestFactory().get("/admin/")
        request.user = actor
        self.assertTrue(admin.site._registry[SubscriptionPlan].has_change_permission(request))
        self.assertFalse(admin.site._registry[SubscriptionPlan].has_delete_permission(request))
        with self.assertRaises(PermissionDenied):
            save_plan_configuration(actor=self.user, instance=self.plan, reason="Denied")

    def test_invoice_requires_explicit_review_and_no_tax_is_not_assumed(self):
        order = self.paid()
        with self.assertRaises(ValidationError):
            self.document(order)
        save_configuration(actor=self.actor, configuration=BillingConfiguration(seller_name="Draft", seller_address="Draft"),
                           reason="Draft only", reviewed=False)
        with self.assertRaises(ValidationError):
            self.document(order)
        self.config()
        document = self.document(order)
        self.assertEqual(document.tax_amount, Decimal("0"))
        self.assertEqual(document.subtotal, Decimal("118.00"))
        self.assertEqual(document.seller_snapshot["tax_registered"], False)

    def test_tax_configuration_validation_and_config_change_audit(self):
        for values in ({"tax_mode": "inclusive"}, {"tax_components": [{"name": "Tax", "rate": "NaN"}]},
                       {"tax_registered": True}, {"tax_mode": "none", "tax_components": [{"name": "Tax", "rate": "5"}]}):
            with self.assertRaises(ValidationError):
                self.config(**values)
        config = self.config()
        config.financial_retention_days = 900
        save_configuration(actor=self.actor, configuration=config, reason="Retention reviewed", reviewed=True)
        self.assertEqual(FinancialAuditEvent.objects.filter(action="configuration_saved").count(), 2)

    def test_inclusive_tax_snapshot_and_credit_note_copy_original(self):
        order = self.paid()
        self.config(tax_registered=True, tax_registration_number="DECLARED-TEST-ID", tax_mode="inclusive",
                    tax_components=[{"name": "Component A", "rate": "9"}, {"name": "Component B", "rate": "9"}])
        invoice = self.document(order)
        self.assertEqual((invoice.subtotal, invoice.tax_amount, invoice.total), (Decimal("100"), Decimal("18"), Decimal("118")))
        self.assertEqual([row["amount"] for row in invoice.tax_snapshot["components"]], ["9.00", "9.00"])
        self.config(seller_name="New seller configuration")
        simulate_payment(actor=self.actor, order=order, outcome="full_refund", event_key="refund")
        note = self.document(order, kind="credit_note")
        self.assertEqual(note.original_invoice, invoice)
        self.assertEqual(note.seller_snapshot, invoice.seller_snapshot)
        self.assertEqual(note.tax_snapshot, invoice.tax_snapshot)
        self.assertEqual(note.total, invoice.total)
        self.assertEqual(note.refund.order, order)

    def test_document_idempotency_and_immutable_snapshots(self):
        self.config()
        order = self.paid()
        first = issue_document(actor=self.actor, order=order, reason="Issue", event_key="invoice-key")
        self.assertEqual(issue_document(actor=self.actor, order=order, reason="Issue", event_key="invoice-key"), first)
        self.assertEqual(BillingDocument.objects.count(), 1)
        first.total = Decimal("1")
        with self.assertRaises(ValidationError):
            first.save(_financial=True)
        for model in (BillingDocument, FinancialAuditEvent, RefundApproval, Settlement, ReconciliationRecord):
            with self.assertRaises(ValidationError):
                model.objects.all().delete()
        event = FinancialAuditEvent.objects.first()
        event.reason = "Rewritten"
        with self.assertRaises(ValidationError):
            event.save(_financial=True)

    def test_india_financial_year_and_small_amount_rounding(self):
        self.assertEqual(financial_year(date(2026, 3, 31)), "2025-26")
        self.assertEqual(financial_year(date(2026, 4, 1)), "2026-27")
        config = self.config(tax_registered=True, tax_registration_number="TEST", tax_mode="inclusive",
            tax_components=[{"name": f"Component {index}", "rate": "9"} for index in range(6)])
        net, tax, breakdown = tax_totals(Decimal("0.03"), config)
        self.assertEqual(net + tax, Decimal("0.03"))
        self.assertEqual(sum(Decimal(row["amount"]) for row in breakdown["components"]), tax)
        self.assertTrue(all(Decimal(row["amount"]) >= 0 for row in breakdown["components"]))

    def test_refund_approver_is_separate_from_payment_operator(self):
        order = self.paid()
        approver = self.staff("approve_refunds")
        approval = approve_refund(actor=approver, order=order, reason="Refund approved after review", event_key="approval")
        self.assertEqual(approval.actor, approver)
        self.assertEqual(approve_refund(actor=approver, order=order, reason="Refund approved after review", event_key="approval"), approval)
        operator = self.staff("manage_subscriptions")
        operator.user_permissions.add(Permission.objects.get(codename="run_simulated_payments"))
        paid = simulate_payment(actor=operator, order=order, outcome="full_refund", event_key="confirmed-refund")
        self.assertEqual(paid.status, "refunded")
        self.assertEqual(Refund.objects.get().approved_by, approver)
        with self.assertRaises(PermissionDenied):
            approve_refund(actor=operator, order=self.paid(), reason="Denied", event_key="denied")

    def test_settlement_reconciliation_corrections_append(self):
        order = self.paid()
        settlement = record_settlement(actor=self.actor, reference="settlement-1", provider="simulated",
            gross_amount=Decimal("118"), gateway_fee=Decimal("2"), fee_tax=Decimal("0"), net_amount=Decimal("116"),
            settled_at=timezone.now(), reason="Statement imported", event_key="settlement-record")
        payment = PaymentTransaction.objects.get(order=order)
        mismatch = record_reconciliation(actor=self.actor, target_kind="payment", target_id=payment.pk,
            observed_amount=Decimal("117"), statement_reference="statement-line", reason="Mismatch", event_key="mismatch", settlement=settlement)
        matched = record_reconciliation(actor=self.actor, target_kind="payment", target_id=payment.pk,
            observed_amount=Decimal("118"), statement_reference="statement-line-corrected", reason="Corrected statement reference", event_key="matched", settlement=settlement)
        self.assertEqual(latest_reconciliation(payment), matched)
        self.assertEqual(mismatch.status, "mismatch")
        self.assertEqual(payment.reconciliations.count(), 2)
        self.assertEqual(record_reconciliation(actor=self.actor, target_kind="payment", target_id=payment.pk,
            observed_amount=Decimal("118"), statement_reference="statement-line-corrected", reason="Corrected statement reference", event_key="matched", settlement=settlement), matched)
        self.assertEqual(payment.reconciliations.count(), 2)
        self.assertEqual(latest_reconciliation(settlement), None)

    def test_retention_review_does_not_authorize_deletion(self):
        self.config(financial_retention_days=30, audit_retention_days=10)
        order = self.paid()
        self.assertFalse(retention_review(order)["eligible"])
        self.assertTrue(retention_review(order, at=order.created_at + timedelta(days=31))["eligible"])
        with self.assertRaises(ValidationError):
            order.delete()
        config = BillingConfiguration.objects.get()
        config.legal_hold = True
        save_configuration(actor=self.actor, configuration=config, reason="Legal hold", reviewed=True)
        self.assertFalse(retention_review(order, at=order.created_at + timedelta(days=99))["eligible"])

    def test_sales_payments_refunds_tax_and_empty_settlement_csvs(self):
        self.config(tax_registered=True, tax_registration_number="TEST", tax_mode="inclusive",
            tax_components=[{"name": "Reviewed component", "rate": "18"}])
        order = self.paid()
        self.document(order)
        simulate_payment(actor=self.actor, order=order, outcome="full_refund", event_key="refund-export")
        self.document(order, kind="credit_note")
        sales = list(csv.DictReader(io.StringIO(export_csv(actor=self.actor, report="sales", reason="Accounting handoff"))))
        self.assertEqual(sales[0]["amount"], "118.00")
        self.assertEqual(sales[0]["tax_amount"], "18.00")
        self.assertNotIn("email", sales[0])
        for report in ("payments", "refunds"):
            rows = list(csv.DictReader(io.StringIO(export_csv(actor=self.actor, report=report, reason="Accounting handoff"))))
            self.assertEqual(len(rows), 1)
        tax = list(csv.DictReader(io.StringIO(export_csv(actor=self.actor, report="tax", reason="Accounting handoff"))))
        self.assertEqual(Decimal(tax[0]["net_tax_amount"]), 0)
        self.assertEqual(Decimal(tax[0]["net_taxable_amount"]), 0)
        self.assertEqual(len(list(csv.reader(io.StringIO(export_csv(actor=self.actor, report="settlements", reason="No gateway settlement yet"))))), 1)
        self.assertEqual(FinancialAuditEvent.objects.filter(action="csv_export").count(), 5)
        self.assertEqual(len(FinancialAuditEvent.objects.filter(action="csv_export").first().after["sha256"]), 64)

    def test_export_date_filters_and_csv_formula_neutralization(self):
        self.plan.name = '=HYPERLINK("unsafe")'
        self.plan.save()
        self.paid()
        text = export_csv(actor=self.actor, report="sales", reason="Safe export")
        self.assertIn("'=HYPERLINK", text)
        tomorrow = timezone.now().astimezone(INDIA).date() + timedelta(days=1)
        self.assertEqual(len(list(csv.reader(io.StringIO(export_csv(actor=self.actor, report="sales", reason="Date range", start=tomorrow))))), 1)
        with self.assertRaises(ValidationError):
            export_csv(actor=self.actor, report="sales", reason="Invalid range", start=date(2027, 1, 1), end=date(2026, 1, 1))

    def test_admin_operations_export_permissions_csrf_and_audited_download(self):
        self.config()
        order = self.paid()
        self.client.force_login(self.actor)
        url = reverse("admin:billing_finance_operation", args=["invoice"])
        data = {"order": order.pk, "reason": "Invoice issue", "event_key": uuid4()}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        export_url = reverse("admin:billing_finance_export")
        response = self.client.post(export_url, {"report": "sales", "reason": "Accountant handoff"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.actor)
        self.assertEqual(protected.post(export_url, {"report": "sales", "reason": "Denied"}).status_code, 403)
        viewer = self.staff("view_financial_records")
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(export_url, {"report": "sales", "reason": "Denied"}).status_code, 403)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_admin_plan_manager_edits_require_a_reason(self):
        manager = self.staff("manage_plans")
        self.client.force_login(manager)
        url = reverse("admin:billing_subscriptionplan_change", args=[self.plan.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        data = {"code": self.plan.code, "name": self.plan.name, "tier": "premium", "price": "199.00",
                "currency": "INR", "duration_days": "30", "is_active": "on"}
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.price, Decimal("118.00"))
        data["audit_reason"] = "Reviewed administrative price change"
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.price, Decimal("199.00"))
        self.assertEqual(FinancialAuditEvent.objects.get(action="plan_configuration_saved").actor, manager)

    def test_admin_configuration_review_and_read_only_plan_inspection(self):
        reviewer = self.staff("manage_financial_configuration")
        self.client.force_login(reviewer)
        url = reverse("admin:billing_billingconfiguration_add")
        self.assertEqual(self.client.get(url).status_code, 200)
        data = {"seller_name": "Reviewed seller", "seller_address": "Test seller address",
            "tax_registered": "false", "tax_registration_number": "", "tax_mode": "none", "tax_components": "[]",
            "invoice_prefix": "INV", "credit_note_prefix": "CN", "reviewed": "on", "audit_reason": "Reviewed seller/tax/retention policy"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(BillingConfiguration.objects.get().reviewed_by, reviewer)
        configure_roles()
        viewer = self.staff("grant_premium")
        viewer.groups.add(Group.objects.get(name="Billing Premium granter"))
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(reverse("admin:billing_subscriptionplan_change", args=[self.plan.pk])).status_code, 200)
        lifecycle = self.client.get(reverse("admin:billing_usersubscription_lifecycle"))
        self.assertEqual(lifecycle.status_code, 200)
        self.assertEqual([key for key, _ in lifecycle.context["form"].fields["operation"].choices], ["activate", "renew"])

    def test_postgres_guards_prevent_raw_history_edits_deletes_and_finalization_reversal(self):
        self.config()
        order = self.paid()
        invoice = self.document(order)
        statements = [
            ("UPDATE billing_billingdocument SET total = total + 1 WHERE id = %s", invoice.pk),
            ("DELETE FROM billing_billingdocument WHERE id = %s", invoice.pk),
            ("UPDATE billing_financialauditevent SET reason = 'rewritten' WHERE id = %s", FinancialAuditEvent.objects.first().pk),
            ("UPDATE billing_paymentorder SET status = 'pending' WHERE id = %s", order.pk),
            ("UPDATE billing_paymenttransaction SET status = 'pending' WHERE order_id = %s", order.pk),
        ]
        for sql, pk in statements:
            with self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql, [pk])
        invoice.refresh_from_db()
        self.assertEqual(invoice.total, Decimal("118.00"))


@override_settings(BILLING_SIMULATION_ENABLED=True, DEBUG=True, IS_PRODUCTION=False, DJANGO_ENV="dev")
class ConcurrentInvoiceTests(FinanceFixture, TransactionTestCase):
    def setUp(self):
        self.configure()
        self.config()

    def race(self, orders):
        barrier = Barrier(2)
        def issue(order):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.document(order).number
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(issue, orders))

    def test_concurrent_invoice_numbers_are_unique(self):
        numbers = self.race([self.paid(), self.paid()])
        self.assertEqual(len(set(numbers)), 2)
        self.assertEqual(BillingDocument.objects.count(), 2)

    def test_concurrent_issuance_for_same_order_is_idempotent(self):
        order = self.paid()
        numbers = self.race([order, order])
        self.assertEqual(numbers[0], numbers[1])
        self.assertEqual(BillingDocument.objects.count(), 1)
