from uuid import uuid4
from django import forms
from .models import BillingConfiguration, PlanEntitlement, SubscriptionPlan, PaymentOrder, Settlement
from .exports import REPORTS


class PlanAdminForm(forms.ModelForm):
    audit_reason = forms.CharField(max_length=500, widget=forms.Textarea)
    class Meta:
        model = SubscriptionPlan
        fields = "__all__"


class EntitlementAdminForm(PlanAdminForm):
    class Meta:
        model = PlanEntitlement
        fields = "__all__"


class ConfigurationAdminForm(forms.ModelForm):
    audit_reason = forms.CharField(max_length=500, widget=forms.Textarea)
    reviewed = forms.BooleanField(required=False, label="I have reviewed the seller, tax treatment and retention settings")
    class Meta:
        model = BillingConfiguration
        exclude = ("created_at", "reviewed_at", "reviewed_by")


class OperationForm(forms.Form):
    reason = forms.CharField(max_length=500, widget=forms.Textarea)
    event_key = forms.UUIDField(initial=uuid4, widget=forms.HiddenInput)


class DocumentForm(OperationForm):
    order = forms.ModelChoiceField(queryset=PaymentOrder.objects.filter(status__in=["paid", "refunded"]))


class RefundApprovalForm(OperationForm):
    order = forms.ModelChoiceField(queryset=PaymentOrder.objects.filter(status="paid"))


class SettlementForm(OperationForm):
    reference = forms.CharField(max_length=128)
    provider = forms.CharField(max_length=24)
    gross_amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    gateway_fee = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    fee_tax = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    net_amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    settled_at = forms.DateTimeField(help_text="Use a timezone-aware timestamp; no settlement or fee is invented.")


class ReconciliationForm(OperationForm):
    target_kind = forms.ChoiceField(choices=[("payment", "Payment"), ("settlement", "Settlement")])
    target_id = forms.IntegerField(min_value=1)
    observed_amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    statement_reference = forms.CharField(max_length=128)
    settlement = forms.ModelChoiceField(queryset=Settlement.objects.all(), required=False,
                                      help_text="Optional settlement association for a payment.")
    status = forms.ChoiceField(choices=[("", "Calculate matched/mismatch"), ("unreconciled", "Reopen for review")], required=False)


class ExportForm(forms.Form):
    report = forms.ChoiceField(choices=[(kind, kind.replace("_", " ").title()) for kind in REPORTS])
    start = forms.DateField(required=False, help_text="Inclusive date in Asia/Kolkata.")
    end = forms.DateField(required=False)
    reason = forms.CharField(max_length=500)
