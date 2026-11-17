"""Contract for future server-side provider adapters; no gateway or activation wired."""
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction


@dataclass(frozen=True)
class VerifiedSubscription:
    """Provider-verified facts, never browser-supplied activation instructions."""
    reference: str
    plan_code: str
    starts_at: datetime
    ends_at: datetime


class SubscriptionProvider(Protocol):
    def verify_subscription(self, reference: str) -> VerifiedSubscription:
        """Verify provider state server-side; persistence needs a future trusted workflow."""
        ...


@dataclass(frozen=True)
class VerifiedPayment:
    provider: str
    event_reference: str
    order_reference: str
    transaction_reference: str
    outcome: str
    amount: str
    currency: str


class PaymentProvider(Protocol):
    """Future Razorpay/Cashfree adapters must verify authenticity server-side.

    Never turn browser status or an unverified webhook body into this result.
    B4 implements only the explicitly enabled local simulator.
    """
    def create_order(self, reference: str, amount: str, currency: str) -> str: ...
    def verify_event(self, reference: str) -> VerifiedPayment: ...


def simulation_enabled():
    return (settings.BILLING_SIMULATION_ENABLED is True and settings.DEBUG is True
            and not settings.IS_PRODUCTION and settings.DJANGO_ENV != "prod")


def require_simulator(actor=None):
    if not simulation_enabled():
        raise PermissionDenied("Simulated payments are disabled.")
    if actor is not None and (not actor.is_authenticated or not actor.is_active or not actor.is_staff
            or not actor.has_perm("billing.run_simulated_payments")
            or not actor.has_perm("billing.manage_subscriptions")):
        raise PermissionDenied("Authorized billing test access is required.")


class SimulatedProvider:
    def create_order(self, reference, amount, currency):
        require_simulator()
        return f"sim-order:{reference}"

    def verify_event(self, reference):
        require_simulator()
        from .models import PaymentEvent
        event = PaymentEvent.objects.select_related("order").get(reference=reference, provider="simulated")
        return VerifiedPayment(event.provider, event.reference, event.order.provider_reference,
            event.transaction_reference, event.outcome, str(event.amount), event.currency)

    def record_event(self, *, actor, order, outcome, event_key):
        require_simulator(actor)
        from .models import PaymentEvent
        if outcome not in {"success", "failed", "pending", "full_refund"}:
            raise ValidationError("Choose a supported simulated outcome.")
        if not isinstance(event_key, str) or not event_key.strip() or len(event_key) > 80:
            raise ValidationError("Provide a simulator event key of at most 80 characters.")
        reference = f"sim-event:{event_key}"
        existing = PaymentEvent.objects.filter(reference=reference).first()
        if existing:
            if existing.order_id != order.pk or existing.outcome != outcome:
                raise ValidationError("This simulator event key belongs to another request.")
            return existing
        event = PaymentEvent(provider="simulated", reference=reference, order=order,
            transaction_reference=f"sim-pay:{order.reference}", outcome=outcome,
            amount=order.amount, currency=order.currency, actor=actor)
        try:
            with transaction.atomic():
                event.save(_financial=True)
        except IntegrityError:
            raise ValidationError("This simulator event key has already been used.")
        return event


def payment_provider(name="simulated") -> PaymentProvider:
    if name != "simulated":
        raise ValidationError("No real payment provider is configured.")
    require_simulator()
    return SimulatedProvider()
