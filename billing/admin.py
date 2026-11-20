from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.http import HttpResponse
from django.urls import path, reverse
from uuid import uuid4

from .models import (FreeExamSelection, FreeMockSelection, FreeQuestionUsage,
                     BillingConfiguration, BillingDocument, FinancialAuditEvent, RefundApproval,
                     Settlement, ReconciliationRecord,
                     PaymentEvent, PaymentOrder, PaymentTransaction, Refund,
                     PlanEntitlement, SubscriptionEvent, SubscriptionPlan, UserSubscription)


class ReadOnlyHistoryAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class FinancialHistoryAdmin(ReadOnlyHistoryAdmin):
    def has_view_permission(self, request, obj=None):
        return request.user.has_perm("billing.view_financial_records") or super().has_view_permission(request, obj)


class PlanConfigurationAdmin(admin.ModelAdmin):
    def has_view_permission(self, request, obj=None):
        return request.user.has_perm("billing.manage_plans") or super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return request.user.has_perm("billing.manage_plans")

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("billing.manage_plans")

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        from .finance import save_plan_configuration
        save_plan_configuration(actor=request.user, instance=obj, reason=form.cleaned_data["audit_reason"])

@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(PlanConfigurationAdmin):
    from .finance_forms import PlanAdminForm as form
    list_display = ("code", "name", "tier", "price", "currency", "duration_days", "is_active")
    list_filter = ("tier", "is_active", "duration_days")
    search_fields = ("code", "name")


@admin.register(PlanEntitlement)
class PlanEntitlementAdmin(PlanConfigurationAdmin):
    from .finance_forms import EntitlementAdminForm as form
    list_display = ("plan", "feature", "is_enabled", "usage_limit", "usage_period")
    list_filter = ("feature", "is_enabled", "plan")
    list_select_related = ("plan",)


@admin.register(UserSubscription)
class UserSubscriptionAdmin(FinancialHistoryAdmin):
    list_display = ("id", "user", "plan", "status", "starts_at", "ends_at")
    list_filter = ("status", "plan")
    list_select_related = ("user", "plan")
    change_list_template = "admin/billing/subscription_changelist.html"

    def get_urls(self):
        return [path("lifecycle/", self.admin_site.admin_view(self.lifecycle_view),
                     name="billing_usersubscription_lifecycle")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, extra_context={
            **(extra_context or {}), "can_manage_subscriptions": any(request.user.has_perm(f"billing.{code}") for code in ("manage_subscriptions", "grant_premium", "approve_refunds"))})

    def lifecycle_view(self, request):
        if not any(request.user.has_perm(f"billing.{code}") for code in ("manage_subscriptions", "grant_premium", "approve_refunds")):
            raise PermissionDenied
        from .forms import SubscriptionLifecycleForm
        from . import lifecycle
        form = SubscriptionLifecycleForm(request.POST if request.method == "POST" else None, actor=request.user)
        if request.method == "POST" and form.is_valid():
            values = form.cleaned_data
            common = dict(actor=request.user, event_key=str(values["event_key"]), reason=values["reason"])
            try:
                if values["operation"] in {"activate", "renew"}:
                    service = lifecycle.activate_subscription if values["operation"] == "activate" else lifecycle.renew_subscription
                    subscription = service(user=values["user"], plan=values["plan"], **common)
                else:
                    services = {"expire": lifecycle.expire_subscription, "revoke": lifecycle.revoke_subscription,
                                "full_refund": lifecycle.revoke_for_full_refund}
                    if values["operation"] == "full_refund":
                        common["refund_reference"] = values["refund_reference"]
                    subscription = services[values["operation"]](subscription=values["subscription"], **common)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                self.message_user(request, "Subscription lifecycle event recorded.")
                return redirect(reverse("admin:billing_usersubscription_change", args=[subscription.pk]))
        context = {**self.admin_site.each_context(request), "title": "Manage Premium subscription",
                   "opts": self.model._meta, "form": form}
        return TemplateResponse(request, "admin/billing/lifecycle.html", context,
                                status=400 if form.errors else 200)


@admin.register(SubscriptionEvent)
class SubscriptionEventAdmin(FinancialHistoryAdmin):
    list_display = ("event_key", "kind", "subscription", "actor", "effective_at", "created_at")
    list_filter = ("kind",)
    search_fields = ("event_key",)
    list_select_related = ("subscription__plan", "actor")


class LifetimeAllocationAdmin(ReadOnlyHistoryAdmin):
    """Allow permission-gated inspection without resetting lifetime allowances."""


@admin.register(FreeExamSelection)
class FreeExamSelectionAdmin(LifetimeAllocationAdmin):
    list_display = ("user", "exam", "selected_at")
    list_select_related = ("user", "exam")


@admin.register(FreeMockSelection)
class FreeMockSelectionAdmin(LifetimeAllocationAdmin):
    list_display = ("user", "pattern", "selected_at")
    list_select_related = ("user", "pattern")


@admin.register(FreeQuestionUsage)
class FreeQuestionUsageAdmin(LifetimeAllocationAdmin):
    list_display = ("user", "question_id", "delivered_at")
    list_select_related = ("user",)


@admin.register(PaymentOrder)
class PaymentOrderAdmin(FinancialHistoryAdmin):
    list_display = ("reference", "user", "provider", "amount", "currency", "status", "created_at")
    list_filter = ("provider", "status")
    search_fields = ("reference", "provider_reference")
    list_select_related = ("user",)
    change_form_template = "admin/billing/payment_order.html"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        from .views import can_simulate
        return super().change_view(request, object_id, form_url, extra_context={
            **(extra_context or {}), "can_simulate": can_simulate(request.user), "simulation_key": uuid4(),
            "can_refund": request.user.has_perm("billing.approve_refunds") or RefundApproval.objects.filter(order_id=object_id).exists()})


@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(FinancialHistoryAdmin):
    list_display = ("id", "reference", "order", "status", "amount", "currency", "created_at", "reconciliation_status")
    list_filter = ("status", "provider")
    list_select_related = ("order",)

    @admin.display(description="Reconciliation")
    def reconciliation_status(self, obj):
        from .finance import latest_reconciliation
        record = latest_reconciliation(obj)
        return record.status if record else "unreconciled"


@admin.register(PaymentEvent)
class PaymentEventAdmin(FinancialHistoryAdmin):
    list_display = ("reference", "order", "outcome", "result", "actor", "created_at")
    list_filter = ("outcome", "result", "provider")
    list_select_related = ("order", "actor")


@admin.register(Refund)
class RefundAdmin(FinancialHistoryAdmin):
    list_display = ("reference", "order", "amount", "currency", "approved_by", "created_at")
    list_select_related = ("order", "approved_by")


@admin.register(BillingConfiguration)
class BillingConfigurationAdmin(FinancialHistoryAdmin):
    from .finance_forms import ConfigurationAdminForm as form
    readonly_fields = ("reviewed_by", "reviewed_at", "created_at")
    def has_add_permission(self, request):
        return request.user.has_perm("billing.manage_financial_configuration") and not BillingConfiguration.objects.exists()

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm("billing.manage_financial_configuration")

    def has_view_permission(self, request, obj=None):
        return self.has_change_permission(request, obj) or super().has_view_permission(request, obj)

    def save_model(self, request, obj, form, change):
        from .accounting import save_configuration
        save_configuration(actor=request.user, configuration=obj, reason=form.cleaned_data["audit_reason"], reviewed=form.cleaned_data["reviewed"])


@admin.register(BillingDocument)
class BillingDocumentAdmin(FinancialHistoryAdmin):
    list_display = ("number", "kind", "financial_year", "invoice_date", "order", "subtotal", "tax_amount", "total")
    list_filter = ("kind", "financial_year", "invoice_date")
    search_fields = ("number", "customer_reference")
    list_select_related = ("order",)


@admin.register(RefundApproval)
class RefundApprovalAdmin(FinancialHistoryAdmin):
    list_display = ("order", "actor", "reason", "created_at")
    list_select_related = ("order", "actor")


class ReconciliationStatusMixin:
    @admin.display(description="Reconciliation")
    def reconciliation_status(self, obj):
        from .finance import latest_reconciliation
        row = latest_reconciliation(obj)
        return row.status if row else "unreconciled"


@admin.register(Settlement)
class SettlementAdmin(ReconciliationStatusMixin, FinancialHistoryAdmin):
    list_display = ("id", "reference", "provider", "gross_amount", "gateway_fee", "fee_tax", "net_amount", "settled_at", "reconciliation_status")
    list_filter = ("provider", "settled_at")


@admin.register(ReconciliationRecord)
class ReconciliationRecordAdmin(FinancialHistoryAdmin):
    list_display = ("target_kind", "payment", "settlement", "status", "expected_amount", "observed_amount", "statement_reference", "actor", "created_at")
    list_filter = ("target_kind", "status")
    list_select_related = ("payment", "settlement", "actor")


OPERATIONS = {
    "invoice": ("issue_billing_documents", "Issue invoice record"),
    "credit_note": ("issue_billing_documents", "Issue credit-note record"),
    "refund": ("approve_refunds", "Approve full refund"),
    "settlement": ("reconcile_financial_records", "Record settlement and fees"),
    "reconcile": ("reconcile_financial_records", "Record reconciliation/correction"),
}


@admin.register(FinancialAuditEvent)
class FinancialAuditEventAdmin(FinancialHistoryAdmin):
    list_display = ("action", "actor", "target_type", "target_reference", "reason", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("event_key", "target_reference")
    change_list_template = "admin/billing/finance_changelist.html"

    def get_urls(self):
        return [path("operations/<str:operation>/", self.admin_site.admin_view(self.operation_view), name="billing_finance_operation"),
                path("exports/", self.admin_site.admin_view(self.export_view), name="billing_finance_export")] + super().get_urls()

    def changelist_view(self, request, extra_context=None):
        context = {"finance_operations": [(key, label) for key, (permission, label) in OPERATIONS.items() if request.user.has_perm(f"billing.{permission}")],
                   "can_export": request.user.has_perm("billing.export_financial_records")}
        return super().changelist_view(request, {**(extra_context or {}), **context})

    def operation_view(self, request, operation):
        from . import finance_forms, finance, accounting
        from .audit import require_permission
        if operation not in OPERATIONS:
            raise PermissionDenied
        permission, title = OPERATIONS[operation]
        require_permission(request.user, permission)
        forms = {"invoice": finance_forms.DocumentForm, "credit_note": finance_forms.DocumentForm,
                 "refund": finance_forms.RefundApprovalForm, "settlement": finance_forms.SettlementForm,
                 "reconcile": finance_forms.ReconciliationForm}
        form = forms[operation](request.POST if request.method == "POST" else None)
        if request.method == "POST" and form.is_valid():
            values = dict(form.cleaned_data)
            values["event_key"] = str(values["event_key"])
            try:
                if operation in {"invoice", "credit_note"}:
                    accounting.issue_document(actor=request.user, kind=operation, **values)
                elif operation == "refund":
                    finance.approve_refund(actor=request.user, **values)
                elif operation == "settlement":
                    finance.record_settlement(actor=request.user, **values)
                else:
                    values["status"] = values.get("status") or None
                    finance.record_reconciliation(actor=request.user, **values)
            except (ValidationError, PaymentTransaction.DoesNotExist, Settlement.DoesNotExist) as error:
                form.add_error(None, error if isinstance(error, ValidationError) else "Select an existing payment or settlement ID.")
            else:
                self.message_user(request, "Audited financial operation recorded.")
                return redirect("admin:billing_financialauditevent_changelist")
        return TemplateResponse(request, "admin/billing/finance_operation.html", {
            **self.admin_site.each_context(request), "opts": self.model._meta, "title": title, "form": form}, status=400 if form.errors else 200)

    def export_view(self, request):
        from .audit import require_permission
        from .finance_forms import ExportForm
        from .exports import export_csv
        require_permission(request.user, "view_financial_records")
        require_permission(request.user, "export_financial_records")
        form = ExportForm(request.POST if request.method == "POST" else None)
        if request.method == "POST" and form.is_valid():
            try:
                content = export_csv(actor=request.user, **form.cleaned_data)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                response = HttpResponse(content, content_type="text/csv; charset=utf-8")
                response["Content-Disposition"] = f'attachment; filename="billing-{form.cleaned_data["report"]}.csv"'
                response["Cache-Control"] = "no-store"
                return response
        return TemplateResponse(request, "admin/billing/finance_operation.html", {
            **self.admin_site.each_context(request), "opts": self.model._meta, "title": "Export accounting CSV", "form": form}, status=400 if form.errors else 200)
