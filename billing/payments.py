"""Financial workflow. Browser navigation never confirms payment."""
from decimal import Decimal, DecimalException
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .lifecycle import _authorize, _fulfill_paid_order, _revoke_financial_refund as revoke_for_full_refund, snapshot_plan
from .models import PaymentEvent, PaymentOrder, PaymentTransaction, Refund, SubscriptionPlan
from .providers import payment_provider, require_simulator


@transaction.atomic
def create_order(*, user, plan, checkout_key):
    require_simulator()
    if not user.is_authenticated or not user.is_active or not user.pk:
        raise ValidationError("An active account is required.")
    try:
        checkout_key = UUID(str(checkout_key))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Reload pricing before starting checkout.")
    owner = get_user_model().objects.select_for_update().get(pk=user.pk)
    if not owner.is_active:
        raise ValidationError("An active account is required.")
    existing = PaymentOrder.objects.filter(user=owner, checkout_key=checkout_key).first()
    if existing:
        if existing.plan_id != plan.pk:
            raise ValidationError("This checkout key belongs to another plan.")
        return existing
    plan = SubscriptionPlan.objects.select_for_update().get(pk=plan.pk)
    if not plan.is_active or plan.tier != "premium":
        raise ValidationError("Select an active Premium plan.")
    plan.full_clean()
    order = PaymentOrder(user=owner, plan=plan, checkout_key=checkout_key, provider="simulated",
        amount=plan.price, currency=plan.currency, plan_snapshot=snapshot_plan(plan))
    order.provider_reference = payment_provider().create_order(str(order.reference), str(order.amount), order.currency)
    order.save(_financial=True)
    return order


def _lock_order(order_id):
    user_id = PaymentOrder.objects.values_list("user_id", flat=True).get(pk=order_id)
    get_user_model().objects.select_for_update().get(pk=user_id)
    return PaymentOrder.objects.select_for_update().get(pk=order_id)


@transaction.atomic
def process_payment_event(*, actor, event_reference):
    _authorize(actor)
    receipt = PaymentEvent.objects.get(reference=event_reference)
    if receipt.provider == "simulated":
        require_simulator(actor)
    order = _lock_order(receipt.order_id)
    event = PaymentEvent.objects.select_for_update().get(pk=receipt.pk)
    if event.result != "received":
        return order
    verified = payment_provider(order.provider).verify_event(event.reference)
    try:
        verified_amount = Decimal(verified.amount)
    except (DecimalException, TypeError, ValueError):
        raise ValidationError("Provider confirmation contains an invalid amount.")
    if (verified.provider != order.provider or verified.event_reference != event.reference
            or verified.order_reference != order.provider_reference
            or verified.transaction_reference != event.transaction_reference
            or verified.outcome != event.outcome or verified_amount != order.amount
            or verified.currency != order.currency or event.amount != order.amount or event.currency != order.currency):
        raise ValidationError("Provider confirmation does not match the order.")
    ignored = order.status in {"failed", "refunded"} or (order.status == "paid" and verified.outcome != "full_refund")
    before_status = order.status
    if not ignored:
        if verified.outcome == "full_refund":
            if order.status != "paid" or not order.subscription_id:
                raise ValidationError("Only a successfully paid order can be fully refunded.")
            payment = PaymentTransaction.objects.get(order=order, status="success")
            if payment.reference != verified.transaction_reference:
                raise ValidationError("Refund confirmation does not match the payment.")
            from .models import RefundApproval
            approval = RefundApproval.objects.filter(order=order).first()
            if approval is None:
                raise ValidationError("An authorized full-refund approval is required.")
            refund = Refund(order=order, transaction=payment, event=event,
                reference=f"sim-refund:{order.reference}", amount=order.amount, currency=order.currency,
                approved_by=approval.actor, reason=approval.reason)
            refund.save(_financial=True)
            revoke_for_full_refund(actor=actor, refund=refund)
            order.status = "refunded"
        else:
            payment = PaymentTransaction.objects.filter(order=order).first()
            if payment is None:
                payment = PaymentTransaction(order=order, reference=verified.transaction_reference,
                    provider=order.provider, amount=order.amount, currency=order.currency)
            if payment.reference != verified.transaction_reference:
                raise ValidationError("Provider transaction reference changed.")
            payment.status = verified.outcome
            payment.save(_financial=True)
            if verified.outcome == "success":
                order.subscription = _fulfill_paid_order(actor=actor, order=order)
                order.status = "paid"
            else:
                order.status = verified.outcome
        order.save(_financial=True, update_fields=["status", "subscription"])
    event.result = "ignored" if ignored else "processed"
    event.processed_at = timezone.now()
    event.save(_financial=True, update_fields=["result", "processed_at"])
    from .audit import append_audit
    append_audit(actor=actor, action="payment_event_processed", target=order,
        reason="Verified provider event processing", event_key=f"payment:{event.reference}",
        before={"status": before_status}, after={"status": order.status, "event": event.reference, "result": event.result})
    return order


def simulate_payment(*, actor, order, outcome, event_key):
    require_simulator(actor)
    # Persist the provider receipt first. If fulfillment fails it remains received
    # and auditable, ready for an authorized server-side retry after correction.
    with transaction.atomic():
        locked = _lock_order(order.pk)
        if outcome == "full_refund":
            from .finance import approve_refund
            from .models import RefundApproval
            if not RefundApproval.objects.filter(order=locked).exists():
                approve_refund(actor=actor, order=locked, reason="Authorized simulated full refund",
                    event_key=f"sim-refund-approval:{locked.reference}")
        provider = payment_provider(locked.provider)
        event = provider.record_event(actor=actor, order=locked, outcome=outcome, event_key=event_key)
    return process_payment_event(actor=actor, event_reference=event.reference)


def replay_payment_event(*, actor, order):
    require_simulator(actor)
    event = order.payment_events.order_by("-created_at", "-pk").first()
    if event is None:
        raise ValidationError("There is no simulated event to replay.")
    return process_payment_event(actor=actor, event_reference=event.reference)
