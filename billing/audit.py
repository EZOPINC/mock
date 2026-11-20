import json
from uuid import uuid4

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.forms.models import model_to_dict

from .models import FinancialAuditEvent


def require_permission(actor, permission):
    if not actor.is_authenticated or not actor.is_active or not actor.is_staff or not actor.has_perm(f"billing.{permission}"):
        raise PermissionDenied(f"Billing permission required: {permission}.")


def validate_reason(reason):
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise ValidationError("Provide an audit reason of at most 500 characters.")


def snapshot(instance):
    return json.loads(json.dumps(model_to_dict(instance), cls=DjangoJSONEncoder)) if instance else {}


def append_audit(*, actor, action, target, reason, before=None, after=None, event_key=None):
    validate_reason(reason)
    target_type, reference = target if isinstance(target, tuple) else (
        target._meta.label_lower, str(getattr(target, "reference", None) or target.pk))
    record = FinancialAuditEvent(actor=actor, action=action, target_type=target_type,
        target_reference=reference, reason=reason,
        before=before or {}, after=after or {}, event_key=event_key or str(uuid4()))
    record.save(_financial=True)
    return record
