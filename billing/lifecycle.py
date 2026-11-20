"""Gateway-independent, authorized subscription lifecycle and immutable audit."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import SubscriptionEvent, SubscriptionPlan, UserSubscription


def _authorize(actor, permission="manage_subscriptions"):
    if not actor.is_authenticated or not actor.is_active or not actor.is_staff or not actor.has_perm(f"billing.{permission}"):
        raise PermissionDenied("Billing management permission is required.")


def _time(at):
    value = at if at is not None else timezone.now()
    if timezone.is_naive(value):
        raise ValidationError("Use a timezone-aware timestamp.")
    return value


def _request(actor, user_id, kind, event_key, reason, at, *, permission="manage_subscriptions", **values):
    _authorize(actor, permission)
    if not isinstance(event_key, str) or not event_key.strip() or len(event_key) > 128:
        raise ValidationError("Provide an idempotency key of at most 128 characters.")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise ValidationError("Provide an audit reason of at most 500 characters.")
    effective_at = _time(at)
    owner = get_user_model().objects.select_for_update().get(pk=user_id)
    payload = dict(user_id=user_id, kind=kind, reason=reason, at=at.isoformat() if at else None, **values)
    existing = SubscriptionEvent.objects.select_related("subscription").filter(event_key=event_key).first()
    if existing and existing.request != payload:
        raise ValidationError("This event key belongs to a different lifecycle request.")
    return owner, effective_at, payload, existing


def _record(subscription, actor, kind, event_key, reason, effective_at, payload):
    try:
        with transaction.atomic():
            event = SubscriptionEvent(subscription=subscription, actor=actor, kind=kind,
                event_key=event_key, reason=reason, effective_at=effective_at, request=payload)
            event.save(_lifecycle=True)
    except IntegrityError:
        # Another account may concurrently submit the same global key. The outer
        # lifecycle transaction rolls back its term/status write as well.
        raise ValidationError("This event key has already been used.")


def snapshot_plan(plan, *, source="lifecycle"):
    return dict(code=plan.code, name=plan.name, tier=plan.tier, price=str(plan.price),
                currency=plan.currency, duration_days=plan.duration_days, source=source)


def _issue(actor, user, plan, *, kind, event_key, reason, at, purchase_snapshot=None, permission="grant_premium"):
    extra = {"purchase_snapshot": purchase_snapshot} if purchase_snapshot else {}
    owner, effective_at, payload, existing = _request(actor, user.pk, kind, event_key, reason, at, permission=permission, plan_id=plan.pk, **extra)
    if existing:
        return existing.subscription
    if not owner.is_active:
        raise ValidationError("Premium can only be granted to an active account.")
    plan = SubscriptionPlan.objects.select_for_update().get(pk=plan.pk)
    if (not plan.is_active and not purchase_snapshot) or plan.tier != SubscriptionPlan.Tier.PREMIUM:
        raise ValidationError("Select an active Premium plan.")
    plan.full_clean()
    current = UserSubscription.objects.filter(user=owner, status=UserSubscription.Status.ACTIVE,
        ends_at__gt=effective_at).order_by("-ends_at", "-pk").first()
    if current and kind == SubscriptionEvent.Kind.ACTIVATION:
        raise ValidationError("Premium is already allocated. Use renewal to extend it.")
    start = current.ends_at if current else effective_at
    snapshot = purchase_snapshot if purchase_snapshot else snapshot_plan(plan)
    subscription = UserSubscription(user=owner, plan=plan, starts_at=start,
        ends_at=start + timedelta(days=snapshot["duration_days"]), plan_snapshot=snapshot,
        previous_subscription=current if kind == SubscriptionEvent.Kind.RENEWAL else None)
    subscription.save(_lifecycle=True)
    _record(subscription, actor, kind, event_key, reason, effective_at, payload)
    return subscription


@transaction.atomic
def _fulfill_paid_order(*, actor, order):
    """Internal payment boundary: call only after provider verification under locks.

    Renewal already handles both a first allocation and extension. Reuse that
    calculation with the immutable server-created quote, never browser values.
    """
    return _issue(actor, order.user, order.plan, kind=SubscriptionEvent.Kind.RENEWAL,
        event_key=f"paid-order:{order.reference}", reason=f"Verified {order.provider} payment for order {order.reference}",
        at=None, purchase_snapshot=order.plan_snapshot, permission="manage_subscriptions")


@transaction.atomic
def activate_subscription(*, actor, user, plan, event_key, reason, at=None):
    return _issue(actor, user, plan, kind=SubscriptionEvent.Kind.ACTIVATION,
                  event_key=event_key, reason=reason, at=at)


@transaction.atomic
def renew_subscription(*, actor, user, plan, event_key, reason, at=None):
    return _issue(actor, user, plan, kind=SubscriptionEvent.Kind.RENEWAL,
                  event_key=event_key, reason=reason, at=at)


def _transition(actor, subscription, *, kind, event_key, reason, at, refund_reference=None, permission="manage_subscriptions"):
    owner, effective_at, payload, existing = _request(actor, subscription.user_id, kind, event_key, reason,
        at, permission=permission, subscription_id=subscription.pk, refund_reference=refund_reference)
    if existing:
        return existing.subscription
    subscription = UserSubscription.objects.select_for_update().get(pk=subscription.pk, user=owner)
    if kind == SubscriptionEvent.Kind.EXPIRATION:
        if subscription.ends_at > effective_at:
            raise ValidationError("This subscription term has not expired.")
        if subscription.status == UserSubscription.Status.ACTIVE:
            subscription.status = UserSubscription.Status.EXPIRED
    else:
        subscription.status = UserSubscription.Status.REVOKED
    if not subscription.plan_snapshot:
        # Legacy snapshots are normally populated by migration. Legacy ORM
        # callers remain compatible, but trusted lifecycle transitions freeze
        # the available configuration before changing their status.
        subscription.plan_snapshot = snapshot_plan(subscription.plan, source="legacy_current_configuration")
    subscription.save(_lifecycle=True, update_fields=["status", "plan_snapshot"])
    _record(subscription, actor, kind, event_key, reason, effective_at, payload)
    return subscription


@transaction.atomic
def expire_subscription(*, actor, subscription, event_key, reason, at=None):
    return _transition(actor, subscription, kind=SubscriptionEvent.Kind.EXPIRATION,
                       event_key=event_key, reason=reason, at=at)


@transaction.atomic
def revoke_subscription(*, actor, subscription, event_key, reason, at=None):
    return _transition(actor, subscription, kind=SubscriptionEvent.Kind.REVOCATION,
                       event_key=event_key, reason=reason, at=at)


@transaction.atomic
def revoke_for_full_refund(*, actor, subscription, refund_reference, event_key, reason, at=None):
    """Record an authorized full-refund approval and revoke only its term.

    No payment is processed here. Other independently granted/renewed terms
    retain their dates and status; this never deletes or resets Free state.
    """
    if not isinstance(refund_reference, str) or not refund_reference.strip() or len(refund_reference) > 128:
        raise ValidationError("Provide the approved full-refund reference (at most 128 characters).")
    if hasattr(subscription, "payment_order"):
        raise ValidationError("Use the financial order refund approval workflow for paid subscriptions.")
    return _transition(actor, subscription, kind=SubscriptionEvent.Kind.FULL_REFUND,
        event_key=event_key, reason=reason, at=at, refund_reference=refund_reference, permission="approve_refunds")


def _revoke_financial_refund(*, actor, refund):
    from .models import RefundApproval
    approval = RefundApproval.objects.get(order=refund.order)
    return _transition(actor, refund.order.subscription, kind=SubscriptionEvent.Kind.FULL_REFUND,
        event_key=f"refund-order:{refund.order.reference}", reason=approval.reason, at=None,
        refund_reference=refund.reference, permission="manage_subscriptions")
