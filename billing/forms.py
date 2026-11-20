from uuid import uuid4

from django import forms
from django.contrib.auth import get_user_model

from .models import SubscriptionPlan, UserSubscription


class SubscriptionLifecycleForm(forms.Form):
    operation = forms.ChoiceField(choices=[("activate", "Activate"), ("renew", "Renew"),
        ("expire", "Record expiration"), ("revoke", "Revoke"), ("full_refund", "Approve full refund and revoke")])
    user = forms.ModelChoiceField(queryset=get_user_model().objects.none(), required=False)
    plan = forms.ModelChoiceField(queryset=SubscriptionPlan.objects.none(), required=False)
    subscription = forms.ModelChoiceField(queryset=UserSubscription.objects.none(), required=False,
        help_text="Select a specific term for expiration, revocation or full-refund approval.")
    refund_reference = forms.CharField(max_length=128, required=False)
    event_key = forms.UUIDField(initial=uuid4, widget=forms.HiddenInput)
    reason = forms.CharField(max_length=500, widget=forms.Textarea)

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user"].queryset = get_user_model().objects.filter(is_active=True)
        self.fields["plan"].queryset = SubscriptionPlan.objects.filter(tier="premium", is_active=True)
        self.fields["subscription"].queryset = UserSubscription.objects.select_related("plan")
        if actor is not None:
            permissions = {"activate": "grant_premium", "renew": "grant_premium", "expire": "manage_subscriptions",
                           "revoke": "manage_subscriptions", "full_refund": "approve_refunds"}
            self.fields["operation"].choices = [(key, label) for key, label in self.fields["operation"].choices
                                                if actor.has_perm(f"billing.{permissions[key]}")]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("operation") in {"activate", "renew"}:
            for field in ("user", "plan"):
                if not cleaned.get(field):
                    self.add_error(field, "Required for activation or renewal.")
            if cleaned.get("subscription") or cleaned.get("refund_reference"):
                raise forms.ValidationError("Activation and renewal use the account and plan fields only.")
        else:
            if not cleaned.get("subscription"):
                self.add_error("subscription", "Select the subscription term.")
            if cleaned.get("user") or cleaned.get("plan"):
                raise forms.ValidationError("Use the subscription field for this operation.")
            if cleaned.get("operation") == "full_refund" and not cleaned.get("refund_reference"):
                self.add_error("refund_reference", "Provide the approved full-refund reference.")
            elif cleaned.get("operation") != "full_refund" and cleaned.get("refund_reference"):
                self.add_error("refund_reference", "Only full-refund approvals use this field.")
        return cleaned
