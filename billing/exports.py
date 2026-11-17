"""Stable reference-based CSVs; no account emails or banking data."""
import csv
import io
import hashlib
import json
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import OuterRef, Subquery
from django.db.models.functions import Coalesce

from .accounting import INDIA
from .audit import append_audit, require_permission, validate_reason
from .models import BillingDocument, PaymentEvent, PaymentOrder, PaymentTransaction, Refund, Settlement

REPORTS = {
    "sales": ["order_reference", "customer_reference", "plan", "amount", "currency", "status", "confirmed_at", "invoice_number", "financial_year", "invoice_date", "subtotal", "tax_amount", "tax_breakdown", "seller_details"],
    "payments": ["payment_reference", "order_reference", "provider", "status", "amount", "currency", "recorded_at", "reconciliation_status", "statement_reference", "settlement_reference"],
    "refunds": ["refund_reference", "payment_reference", "order_reference", "amount", "currency", "refunded_at", "credit_note_number", "approved_by"],
    "settlements": ["settlement_reference", "provider", "gross_amount", "gateway_fee", "fee_tax", "net_amount", "currency", "settled_at", "reconciliation_status", "statement_reference"],
    "tax": ["financial_year", "currency", "component", "rate", "net_taxable_amount", "net_tax_amount"],
}


def _range(queryset, field, start, end):
    if start:
        queryset = queryset.filter(**{field + "__gte": datetime.combine(start, time.min, INDIA)})
    if end:
        queryset = queryset.filter(**{field + "__lt": datetime.combine(end + timedelta(days=1), time.min, INDIA)})
    return queryset


def _rows(kind, start, end):
    from .finance import latest_reconciliation
    if kind == "sales":
        rows = PaymentOrder.objects.filter(status__in=["paid", "refunded"]).select_related("subscription")
        for row in _range(rows, "subscription__created_at", start, end).order_by("pk").iterator():
            invoice = row.documents.filter(kind="invoice").first()
            yield [str(row.reference), f"account:{row.user_id}", row.plan_snapshot["name"], row.amount,
                   row.currency, row.status, row.subscription.created_at.isoformat(), invoice.number if invoice else "",
                   invoice.financial_year if invoice else "", str(invoice.invoice_date) if invoice else "",
                   invoice.subtotal if invoice else "", invoice.tax_amount if invoice else "",
                   json.dumps(invoice.tax_snapshot) if invoice else "", json.dumps(invoice.seller_snapshot) if invoice else ""]
    elif kind == "payments":
        processed = PaymentEvent.objects.filter(order_id=OuterRef("order_id"), outcome=OuterRef("status"),
            result="processed").order_by("processed_at").values("processed_at")[:1]
        rows = PaymentTransaction.objects.select_related("order").annotate(accounting_at=Coalesce(Subquery(processed), "created_at"))
        for row in _range(rows, "accounting_at", start, end).order_by("pk").iterator():
            reconciliation = latest_reconciliation(row)
            yield [row.reference, str(row.order.reference), row.provider, row.status, row.amount, row.currency,
                row.accounting_at.isoformat(), reconciliation.status if reconciliation else "unreconciled",
                reconciliation.statement_reference if reconciliation else "",
                reconciliation.settlement.reference if reconciliation and reconciliation.settlement_id else ""]
    elif kind == "refunds":
        rows = Refund.objects.select_related("transaction", "order")
        for row in _range(rows, "created_at", start, end).order_by("pk").iterator():
            note = BillingDocument.objects.filter(refund=row).first()
            yield [row.reference, row.transaction.reference, str(row.order.reference), row.amount, row.currency,
                   row.created_at.isoformat(), note.number if note else "", row.approved_by_id]
    elif kind == "settlements":
        for row in _range(Settlement.objects.all(), "settled_at", start, end).order_by("pk").iterator():
            reconciliation = latest_reconciliation(row)
            yield [row.reference, row.provider, row.gross_amount, row.gateway_fee, row.fee_tax, row.net_amount,
                   row.currency, row.settled_at.isoformat(), reconciliation.status if reconciliation else "unreconciled",
                   reconciliation.statement_reference if reconciliation else ""]
    else:
        rows = BillingDocument.objects.all()
        if start:
            rows = rows.filter(invoice_date__gte=start)
        if end:
            rows = rows.filter(invoice_date__lte=end)
        totals = {}
        for row in rows.iterator():
            sign = Decimal("-1") if row.kind == "credit_note" else Decimal("1")
            components = row.tax_snapshot["components"] or [{"name": "No configured tax", "rate": "0", "amount": "0"}]
            for component in components:
                key = (row.financial_year, row.currency, component["name"], component["rate"])
                base, tax = totals.get(key, (Decimal("0"), Decimal("0")))
                totals[key] = (base + sign * row.subtotal, tax + sign * Decimal(component["amount"]))
        for key, values in sorted(totals.items()):
            yield [*key, *values]


def _safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def export_csv(*, actor, report, reason, start=None, end=None):
    require_permission(actor, "view_financial_records")
    require_permission(actor, "export_financial_records")
    validate_reason(reason)
    if report not in REPORTS or (start and end and start > end):
        raise ValidationError("Choose a supported report and valid date range.")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(REPORTS[report])
    count = 0
    for row in _rows(report, start, end):
        writer.writerow([_safe_cell(cell) for cell in row])
        count += 1
    # Record completed exports, with filters and row count, never their personal data.
    append_audit(actor=actor, action="csv_export", target=("billing.export", report), reason=reason,
        after={"report": report, "start": str(start) if start else None,
               "end": str(end) if end else None, "rows": count,
               "sha256": hashlib.sha256(buffer.getvalue().encode("utf-8")).hexdigest()})
    return buffer.getvalue()
