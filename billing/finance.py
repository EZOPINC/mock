"""Controlled operational changes; financial evidence is never overwritten."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .audit import append_audit, require_permission, snapshot, validate_reason
from .models import (FinancialAuditEvent, PaymentTransaction, ReconciliationRecord,
                     RefundApproval, Settlement, SubscriptionPlan, PlanEntitlement)


@transaction.atomic
def save_plan_configuration(*, actor, instance, reason):
    require_permission(actor, "manage_plans")
    validate_reason(reason)
    if not isinstance(instance, (SubscriptionPlan, PlanEntitlement)):
        raise ValidationError("Only plans and their entitlements use this service.")
    previous = type(instance).objects.select_for_update().filter(pk=instance.pk).first() if instance.pk else None
    before = snapshot(previous)
    instance.full_clean()
    instance.save()
    append_audit(actor=actor, action="plan_configuration_saved", target=instance,
                 reason=reason, before=before, after=snapshot(instance))
    return instance


@transaction.atomic
def approve_refund(*, actor, order, reason, event_key):
    require_permission(actor, "approve_refunds")
    validate_reason(reason)
    from .payments import _lock_order
    order = _lock_order(order.pk)
    if not isinstance(event_key, str) or not event_key.strip() or len(event_key) > 128:
        raise ValidationError("Provide a refund approval event key of at most 128 characters.")
    prior = RefundApproval.objects.filter(event_key=event_key).first()
    if prior and (prior.order_id != order.pk or prior.reason != reason):
        raise ValidationError("This approval key belongs to another request.")
    existing = RefundApproval.objects.filter(order=order).first()
    if existing:
        return existing
    if order.status != "paid":
        raise ValidationError("Only successfully paid orders can be approved for full refund.")
    approval = RefundApproval(order=order, actor=actor, reason=reason, event_key=event_key)
    approval.save(_financial=True)
    append_audit(actor=actor, action="refund_approved", target=approval, reason=reason,
                 after={"order_id": order.pk, "amount": str(order.amount)})
    return approval


def _event_key(key):
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise ValidationError("Provide an operation key of at most 128 characters.")
    return FinancialAuditEvent.objects.filter(event_key=key).first()


@transaction.atomic
def record_settlement(*, actor, reference, provider, gross_amount, gateway_fee, fee_tax,
                      net_amount, settled_at, reason, event_key):
    require_permission(actor, "reconcile_financial_records")
    validate_reason(reason)
    if timezone.is_naive(settled_at):
        raise ValidationError("Use a timezone-aware settlement timestamp.")
    # Serialize reference/idempotency writes without introducing another DB.
    from django.contrib.auth import get_user_model
    get_user_model().objects.select_for_update().get(pk=actor.pk)
    prior = _event_key(event_key)
    values = {"reference": reference, "provider": provider, "gross_amount": str(gross_amount),
        "gateway_fee": str(gateway_fee), "fee_tax": str(fee_tax), "net_amount": str(net_amount),
        "settled_at": settled_at.isoformat()}
    if prior:
        if prior.action != "settlement_recorded" or prior.after != values:
            raise ValidationError("This event key belongs to another operation.")
        return Settlement.objects.get(reference=reference)
    settlement = Settlement(reference=reference, provider=provider, gross_amount=gross_amount,
        gateway_fee=gateway_fee, fee_tax=fee_tax, net_amount=net_amount, settled_at=settled_at, recorded_by=actor)
    settlement.save(_financial=True)
    append_audit(actor=actor, action="settlement_recorded", target=settlement, reason=reason,
                 event_key=event_key, after=values)
    return settlement


@transaction.atomic
def record_reconciliation(*, actor, target_kind, target_id, observed_amount, statement_reference,
                          reason, event_key, status=None, settlement=None):
    require_permission(actor, "reconcile_financial_records")
    validate_reason(reason)
    if target_kind not in {"payment", "settlement"}:
        raise ValidationError("Select payment or settlement reconciliation.")
    model = PaymentTransaction if target_kind == "payment" else Settlement
    target = model.objects.select_for_update().get(pk=target_id)
    if target_kind == "payment" and target.status != "success":
        raise ValidationError("Only successful payments can be reconciled.")
    expected = target.amount if target_kind == "payment" else target.net_amount
    observed = Decimal(str(observed_amount))
    if settlement and (target_kind != "payment" or target.provider != settlement.provider or target.currency != settlement.currency):
        raise ValidationError("Settlement provider/currency must match the payment.")
    if status is None:
        status = "matched" if expected == observed else "mismatch"
    if status not in {"matched", "mismatch", "unreconciled"}:
        raise ValidationError("Select a valid reconciliation status.")
    values = {"target_kind": target_kind, "target_id": target.pk, "observed_amount": str(observed),
        "statement_reference": statement_reference, "status": status,
        "settlement_id": settlement.pk if settlement else None}
    prior = _event_key(event_key)
    if prior:
        if prior.action != "reconciliation_recorded" or prior.after != values:
            raise ValidationError("This event key belongs to another operation.")
        return ReconciliationRecord.objects.get(pk=int(prior.target_reference))
    previous = latest_reconciliation(target)
    record = ReconciliationRecord(target_kind=target_kind, payment=target if target_kind == "payment" else None,
        settlement=settlement if target_kind == "payment" else target, status=status,
        expected_amount=expected, observed_amount=observed, statement_reference=statement_reference, actor=actor, reason=reason)
    record.save(_financial=True)
    append_audit(actor=actor, action="reconciliation_recorded", target=record, reason=reason, event_key=event_key,
                 before=snapshot(previous), after=values)
    return record


def latest_reconciliation(target):
    kind = "payment" if isinstance(target, PaymentTransaction) else "settlement"
    return target.reconciliations.filter(target_kind=kind).first()
