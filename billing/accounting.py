"""Invoice-ready snapshots, not tax advice or an accounting ledger."""
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .audit import append_audit, require_permission, snapshot, validate_reason
from .models import (BillingConfiguration, BillingDocument, DocumentSequence,
                     FinancialAuditEvent, Refund)

INDIA = ZoneInfo("Asia/Kolkata")
CENT = Decimal("0.01")


def validate_tax_configuration(config, *, require_review=True):
    if config.invoice_prefix == config.credit_note_prefix:
        raise ValidationError("Invoice and credit-note prefixes must differ.")
    components = config.tax_components
    if not isinstance(components, list):
        raise ValidationError("Tax components must be a list.")
    names = set()
    rates = []
    for component in components:
        if not isinstance(component, dict) or set(component) != {"name", "rate"} or not isinstance(component["name"], str) or not component["name"].strip():
            raise ValidationError("Each tax component requires a unique name and a decimal rate.")
        try:
            rate = Decimal(str(component["rate"]))
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError("Tax rates must be valid decimals.")
        if not rate.is_finite() or not 0 <= rate <= 100 or component["name"] in names:
            raise ValidationError("Tax rates must be between 0 and 100 with distinct names.")
        names.add(component["name"])
        rates.append(rate)
    if config.tax_mode == "none" and components:
        raise ValidationError("No-tax configuration cannot contain tax components.")
    if config.tax_mode == "inclusive" and (not components or sum(rates) <= 0 or config.tax_registered is not True):
        raise ValidationError("Inclusive tax requires reviewed positive rates and explicit registration status.")
    if config.tax_registered is True and not config.tax_registration_number.strip():
        raise ValidationError("Provide the seller's declared tax registration number.")
    if require_review and (config.tax_mode == "unconfigured" or config.tax_registered is None
            or not config.reviewed_at or not config.reviewed_by_id or not config.seller_name.strip() or not config.seller_address.strip()):
        raise ValidationError("Seller and tax configuration must be explicitly reviewed before issuing documents.")


@transaction.atomic
def save_configuration(*, actor, configuration, reason, reviewed=False):
    require_permission(actor, "manage_financial_configuration")
    validate_reason(reason)
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [8142051])
    previous = BillingConfiguration.objects.select_for_update().filter(pk=1).first()
    before = snapshot(previous)
    configuration.pk = 1
    if previous:
        configuration.created_at = previous.created_at
        configuration._state.adding = False
    configuration.reviewed_by = actor if reviewed else None
    configuration.reviewed_at = timezone.now() if reviewed else None
    configuration.full_clean()
    if reviewed:
        validate_tax_configuration(configuration)
    configuration.save(_financial=True)
    append_audit(actor=actor, action="configuration_saved", target=configuration, reason=reason,
                 before=before, after=snapshot(configuration))
    return configuration


def financial_year(day):
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def tax_totals(gross, configuration):
    if configuration.tax_mode == "none":
        return gross, Decimal("0.00"), {"mode": "none", "components": []}
    components = configuration.tax_components
    rates = [Decimal(str(row["rate"])) for row in components]
    total_rate = sum(rates)
    net = (gross / (1 + total_rate / 100)).quantize(CENT, rounding=ROUND_HALF_UP)
    tax = gross - net
    exact = [tax * rate / total_rate for rate in rates]
    amounts = [value.quantize(CENT, rounding=ROUND_DOWN) for value in exact]
    cents = int((tax - sum(amounts)) / CENT)
    for index in sorted(range(len(rates)), key=lambda i: exact[i] - amounts[i], reverse=True)[:cents]:
        amounts[index] += CENT
    return net, tax, {"mode": "inclusive", "components": [
        {"name": row["name"], "rate": str(rate), "amount": str(amount)}
        for row, rate, amount in zip(components, rates, amounts)]}


def _number(config, kind, day):
    year = financial_year(day)
    sequence = DocumentSequence.objects.select_for_update().filter(financial_year=year, kind=kind).first()
    if sequence is None:
        sequence = DocumentSequence(financial_year=year, kind=kind, value=0)
    sequence.value += 1
    sequence.save(_financial=True)
    prefix = config.invoice_prefix if kind == "invoice" else config.credit_note_prefix
    return f"{prefix}/{year}/{sequence.value:06d}", year


def _retry(key, action, target):
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise ValidationError("Provide an event key of at most 128 characters.")
    prior = FinancialAuditEvent.objects.filter(event_key=key).first()
    if prior and (prior.action != action or prior.after.get("order_id") != target.pk):
        raise ValidationError("This accounting event key belongs to another request.")


@transaction.atomic
def issue_document(*, actor, order, reason, event_key, kind="invoice"):
    require_permission(actor, "issue_billing_documents")
    validate_reason(reason)
    if kind not in {"invoice", "credit_note"}:
        raise ValidationError("Select invoice or credit note.")
    from .payments import _lock_order
    order = _lock_order(order.pk)
    _retry(event_key, f"issue_{kind}", order)
    existing = BillingDocument.objects.filter(order=order, kind=kind).first()
    if existing:
        return existing
    if order.status not in {"paid", "refunded"}:
        raise ValidationError("Only confirmed sales can receive invoice records.")
    config = BillingConfiguration.objects.select_for_update().filter(pk=1).first()
    if config is None:
        raise ValidationError("Review seller and tax configuration before issuing documents.")
    original = None
    refund = None
    if kind == "credit_note":
        original = BillingDocument.objects.filter(order=order, kind="invoice").first()
        refund = Refund.objects.filter(order=order).first()
        if original is None or refund is None or refund.amount != original.total:
            raise ValidationError("A full refund and its original invoice are required.")
        net, tax, tax_snapshot = original.subtotal, original.tax_amount, original.tax_snapshot
        seller = original.seller_snapshot
    else:
        validate_tax_configuration(config)
        net, tax, tax_snapshot = tax_totals(order.amount, config)
        seller = {"name": config.seller_name, "address": config.seller_address,
                  "tax_registered": config.tax_registered, "tax_registration_number": config.tax_registration_number}
    day = timezone.now().astimezone(INDIA).date()
    number, year = _number(config, kind, day)
    document = BillingDocument(kind=kind, number=number, financial_year=year, invoice_date=day,
        order=order, refund=refund, original_invoice=original, customer_reference=f"account:{order.user_id}",
        plan_snapshot=order.plan_snapshot, seller_snapshot=seller, tax_snapshot=tax_snapshot,
        subtotal=net, tax_amount=tax, total=order.amount, currency=order.currency, issued_by=actor)
    document.save(_financial=True)
    append_audit(actor=actor, action=f"issue_{kind}", target=document, reason=reason, event_key=event_key,
                 after={"order_id": order.pk, "number": number, "total": str(order.amount)})
    return document


def retention_review(record, *, at=None):
    config = BillingConfiguration.objects.filter(pk=1).first()
    if config is None or config.legal_hold:
        return {"eligible": False, "reason": "unconfigured_or_legal_hold"}
    days = config.audit_retention_days if isinstance(record, FinancialAuditEvent) else config.financial_retention_days
    if days is None:
        return {"eligible": False, "reason": "indefinite_retention"}
    from datetime import timedelta
    due = record.created_at + timedelta(days=days)
    return {"eligible": (at or timezone.now()) >= due, "review_after": due}
