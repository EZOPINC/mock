from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from uuid import uuid4


class SubscriptionPlan(models.Model):
    class Tier(models.TextChoices):
        FREE = "free", "Free"
        PREMIUM = "premium", "Premium"

    code = models.SlugField(unique=True)
    name = models.CharField(max_length=100)
    tier = models.CharField(max_length=10, choices=Tier.choices)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    currency = models.CharField(max_length=3, choices=[("INR", "INR")], default="INR")
    duration_days = models.PositiveSmallIntegerField(choices=[(d, str(d)) for d in (30, 90, 365)], null=True, blank=True)
    is_active = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(price__gte=0), name="billing_nonnegative_price"),
            models.CheckConstraint(condition=Q(currency="INR"), name="billing_currency_inr"),
            models.CheckConstraint(condition=Q(tier="free", duration_days__isnull=True, price=0) | Q(tier="premium", duration_days__in=[30, 90, 365], duration_days__isnull=False), name="billing_valid_plan"),
            models.UniqueConstraint(fields=["tier"], condition=Q(tier="free"), name="billing_single_free_plan"),
        ]

    def __str__(self):
        return self.name


class PlanEntitlement(models.Model):
    class Feature(models.TextChoices):
        MOCK = "mock", "Mock"
        PRACTICE = "practice", "Practice"
        REVISION = "revision", "Revision"

    class Period(models.TextChoices):
        LIFETIME = "lifetime", "Lifetime"
        DAY = "day", "UTC calendar day"
        SUBSCRIPTION = "subscription", "Subscription term"

    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.CASCADE, related_name="entitlements")
    feature = models.CharField(max_length=20, choices=Feature.choices)
    is_enabled = models.BooleanField(default=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Blank means unlimited; zero permits no usage.")
    usage_period = models.CharField(max_length=20, choices=Period.choices, default=Period.LIFETIME)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["plan", "feature"], name="billing_unique_plan_feature"),
            models.CheckConstraint(condition=Q(feature__in=["mock", "practice", "revision"]), name="billing_valid_feature"),
            models.CheckConstraint(condition=Q(usage_period__in=["lifetime", "day", "subscription"]), name="billing_valid_usage_period"),
        ]

    def clean(self):
        super().clean()
        if self.plan_id and self.plan.tier == SubscriptionPlan.Tier.FREE and self.usage_period == self.Period.SUBSCRIPTION:
            raise ValidationError({"usage_period": "Free has no subscription term."})

    def __str__(self):
        return f"{self.plan}: {self.get_feature_display()}"


class SubscriptionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if self.exclude(plan_snapshot={}).exists():
            raise ValidationError("Use audited subscription lifecycle services.")
        return super().update(**kwargs)

    def delete(self):
        raise ValidationError("Subscription history must be retained.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Use audited subscription lifecycle services.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use audited subscription lifecycle services.")


class UserSubscription(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"
        REVOKED = "revoked", "Revoked"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="billing_subscriptions")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT, related_name="subscriptions")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(help_text="Exclusive end; recorded terms do not change when plan duration changes.")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    plan_snapshot = models.JSONField(default=dict, blank=True)
    previous_subscription = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True,
                                               related_name="renewals")
    objects = SubscriptionQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="billing_valid_subscription_term"),
            models.CheckConstraint(condition=Q(status__in=["active", "cancelled", "expired", "revoked"]), name="billing_valid_subscription_status"),
        ]
        indexes = [models.Index(fields=["user", "status", "ends_at"])]
        permissions = [("manage_subscriptions", "Can manage audited subscription lifecycle")]

    def clean(self):
        super().clean()
        if self.plan_id and self.plan.tier != SubscriptionPlan.Tier.PREMIUM:
            raise ValidationError({"plan": "Only Premium requires a subscription record."})
        for name in ("starts_at", "ends_at"):
            value = getattr(self, name)
            if value is not None and timezone.is_naive(value):
                raise ValidationError({name: "Use a timezone-aware timestamp."})

    def save(self, *args, _lifecycle=False, **kwargs):
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if previous and previous.plan_snapshot:
            if not _lifecycle:
                raise ValidationError("Use audited subscription lifecycle services.")
            for field in self._meta.concrete_fields:
                if field.name != "status" and getattr(previous, field.attname) != getattr(self, field.attname):
                    raise ValidationError("Subscription terms and snapshots cannot change.")
        elif self.plan_snapshot and not _lifecycle:
            raise ValidationError("Use audited subscription lifecycle services.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Subscription history must be retained.")

    def __str__(self):
        return f"Subscription {self.pk or 'new'} ({self.plan})"


class SubscriptionEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Subscription audit events are immutable.")

    def delete(self):
        raise ValidationError("Subscription audit events must be retained.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use audited subscription lifecycle services.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Subscription audit events are immutable.")


class SubscriptionEvent(models.Model):
    class Kind(models.TextChoices):
        ACTIVATION = "activation", "Activation"
        RENEWAL = "renewal", "Renewal"
        EXPIRATION = "expiration", "Expiration"
        REVOCATION = "revocation", "Revocation"
        FULL_REFUND = "full_refund", "Approved full refund"

    event_key = models.CharField(max_length=128, unique=True)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    subscription = models.ForeignKey(UserSubscription, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="subscription_events")
    reason = models.CharField(max_length=500)
    request = models.JSONField()
    effective_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    objects = SubscriptionEventQuerySet.as_manager()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(kind__in=["activation", "renewal", "expiration", "revocation", "full_refund"]), name="billing_valid_event_kind")]

    def save(self, *args, _lifecycle=False, **kwargs):
        if not _lifecycle or self.pk:
            raise ValidationError("Use audited subscription lifecycle services; events are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Subscription audit events must be retained.")


class FreeExamSelection(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="free_exam_selection")
    exam = models.ForeignKey("exams.Exam", on_delete=models.PROTECT)
    selected_at = models.DateTimeField(auto_now_add=True)


class FreeMockSelection(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="free_mock_selection")
    pattern = models.ForeignKey("mock_tests.ExamPattern", on_delete=models.PROTECT)
    selected_at = models.DateTimeField(auto_now_add=True)


class FreeQuestionUsage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="free_question_usage")
    question = models.ForeignKey("questions.Question", on_delete=models.PROTECT)
    delivered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "question"], name="billing_unique_free_question")]


class FinancialQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use financial services; ledger references are immutable.")

    def delete(self):
        raise ValidationError("Financial records must be retained.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Use financial services.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Use financial services.")


class FinancialRecord(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    objects = FinancialQuerySet.as_manager()
    mutable_fields = ()

    class Meta:
        abstract = True

    def save(self, *args, _financial=False, **kwargs):
        if not _financial:
            raise ValidationError("Use financial services.")
        previous = type(self).objects.filter(pk=self.pk).first() if self.pk is not None else None
        if previous:
            for field in self._meta.concrete_fields:
                if field.name not in self.mutable_fields and getattr(previous, field.attname) != getattr(self, field.attname):
                    raise ValidationError("Financial references and snapshots are immutable.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Financial records must be retained.")


class PaymentOrder(FinancialRecord):
    class Status(models.TextChoices):
        CREATED = "created", "Created"
        PENDING = "pending", "Pending"
        FAILED = "failed", "Failed"
        PAID = "paid", "Paid"
        REFUNDED = "refunded", "Refunded"

    reference = models.UUIDField(default=uuid4, unique=True, editable=False)
    checkout_key = models.UUIDField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payment_orders")
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.PROTECT)
    provider = models.CharField(max_length=24)
    provider_reference = models.CharField(max_length=128, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    plan_snapshot = models.JSONField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.CREATED)
    subscription = models.OneToOneField(UserSubscription, on_delete=models.PROTECT, null=True, blank=True, related_name="payment_order")
    mutable_fields = ("status", "subscription")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "checkout_key"], name="billing_unique_checkout_key"),
            models.CheckConstraint(condition=Q(amount__gte=0, currency="INR"), name="billing_valid_order_amount"),
            models.CheckConstraint(condition=Q(status__in=["created", "pending", "failed"], subscription__isnull=True) | Q(status__in=["paid", "refunded"], subscription__isnull=False), name="billing_valid_order_state"),
        ]
        permissions = [("run_simulated_payments", "Can operate simulated payments in a test environment")]

    def __str__(self):
        return str(self.reference)


class PaymentTransaction(FinancialRecord):
    order = models.OneToOneField(PaymentOrder, on_delete=models.PROTECT, related_name="payment_transaction")
    reference = models.CharField(max_length=128, unique=True)
    provider = models.CharField(max_length=24)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=12, choices=[(v, v.title()) for v in ("pending", "failed", "success")])
    mutable_fields = ("status",)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gte=0, currency="INR", status__in=["pending", "failed", "success"]), name="billing_valid_transaction")]


class PaymentEvent(FinancialRecord):
    provider = models.CharField(max_length=24)
    reference = models.CharField(max_length=128, unique=True)
    order = models.ForeignKey(PaymentOrder, on_delete=models.PROTECT, related_name="payment_events")
    transaction_reference = models.CharField(max_length=128)
    outcome = models.CharField(max_length=16, choices=[(v, v.title()) for v in ("pending", "failed", "success", "full_refund")])
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    result = models.CharField(max_length=12, choices=[("received", "Received"), ("processed", "Processed"), ("ignored", "Ignored")], default="received")
    processed_at = models.DateTimeField(null=True, blank=True)
    mutable_fields = ("result", "processed_at")

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0, currency="INR", outcome__in=["pending", "failed", "success", "full_refund"]), name="billing_valid_payment_event"),
            models.CheckConstraint(condition=Q(result="received", processed_at__isnull=True) | Q(result__in=["processed", "ignored"], processed_at__isnull=False), name="billing_valid_event_processing"),
        ]


class Refund(FinancialRecord):
    order = models.OneToOneField(PaymentOrder, on_delete=models.PROTECT, related_name="refund")
    transaction = models.ForeignKey(PaymentTransaction, on_delete=models.PROTECT)
    event = models.OneToOneField(PaymentEvent, on_delete=models.PROTECT)
    reference = models.CharField(max_length=128, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gte=0, currency="INR"), name="billing_valid_refund_amount")]


class FinancialAuditEvent(FinancialRecord):
    event_key = models.CharField(max_length=128, unique=True)
    action = models.CharField(max_length=64)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    target_type = models.CharField(max_length=64)
    target_reference = models.CharField(max_length=128)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)

    class Meta:
        permissions = [
            ("view_financial_records", "Can view financial records"),
            ("manage_plans", "Can manage subscription plans"),
            ("grant_premium", "Can grant Premium manually"),
            ("approve_refunds", "Can approve full refunds"),
            ("manage_financial_configuration", "Can review seller, tax and retention configuration"),
            ("issue_billing_documents", "Can issue invoice and credit-note records"),
            ("reconcile_financial_records", "Can record settlements and reconciliation"),
            ("export_financial_records", "Can export accounting CSV reports"),
        ]


class BillingConfiguration(FinancialRecord):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    seller_name = models.CharField(max_length=200)
    seller_address = models.TextField()
    tax_registered = models.BooleanField(null=True, blank=True)
    tax_registration_number = models.CharField(max_length=40, blank=True)
    tax_mode = models.CharField(max_length=16, choices=[("unconfigured", "Unconfigured"),
        ("none", "No tax, as reviewed"), ("inclusive", "Configured tax included in price")], default="unconfigured")
    tax_components = models.JSONField(default=list, blank=True,
        help_text='Reviewed components, e.g. [{"name": "Tax component", "rate": "0.00"}]. No rates are assumed.')
    invoice_prefix = models.SlugField(max_length=12, default="INV")
    credit_note_prefix = models.SlugField(max_length=12, default="CN")
    financial_retention_days = models.PositiveIntegerField(null=True, blank=True, help_text="Blank means indefinite retention. No automatic deletion.")
    audit_retention_days = models.PositiveIntegerField(null=True, blank=True)
    legal_hold = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    mutable_fields = ("seller_name", "seller_address", "tax_registered", "tax_registration_number", "tax_mode",
        "tax_components", "invoice_prefix", "credit_note_prefix", "financial_retention_days", "audit_retention_days",
        "legal_hold", "reviewed_by", "reviewed_at")

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(id=1), name="billing_single_configuration")]

    def clean(self):
        super().clean()
        from .accounting import validate_tax_configuration
        validate_tax_configuration(self, require_review=False)


class RefundApproval(FinancialRecord):
    order = models.OneToOneField(PaymentOrder, on_delete=models.PROTECT, related_name="refund_approval")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    event_key = models.CharField(max_length=128, unique=True)


class DocumentSequence(FinancialRecord):
    financial_year = models.CharField(max_length=7)
    kind = models.CharField(max_length=12)
    value = models.PositiveIntegerField(default=0)
    mutable_fields = ("value",)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["financial_year", "kind"], name="billing_document_sequence")]


class BillingDocument(FinancialRecord):
    kind = models.CharField(max_length=12, choices=[("invoice", "Invoice"), ("credit_note", "Credit note")])
    number = models.CharField(max_length=64, unique=True)
    financial_year = models.CharField(max_length=7)
    invoice_date = models.DateField()
    order = models.ForeignKey(PaymentOrder, on_delete=models.PROTECT, related_name="documents")
    refund = models.OneToOneField(Refund, on_delete=models.PROTECT, null=True, blank=True, related_name="credit_note")
    original_invoice = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True)
    customer_reference = models.CharField(max_length=128)
    plan_snapshot = models.JSONField()
    seller_snapshot = models.JSONField()
    tax_snapshot = models.JSONField()
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order"], condition=Q(kind="invoice"), name="billing_one_invoice_per_order"),
            models.CheckConstraint(condition=Q(kind="invoice", refund__isnull=True, original_invoice__isnull=True) | Q(kind="credit_note", refund__isnull=False, original_invoice__isnull=False), name="billing_valid_document_kind"),
            models.CheckConstraint(condition=Q(subtotal__gte=0, tax_amount__gte=0, total=F("subtotal") + F("tax_amount"), currency="INR"), name="billing_valid_document_totals"),
        ]

    def __str__(self):
        return self.number


class Settlement(FinancialRecord):
    reference = models.CharField(max_length=128, unique=True)
    provider = models.CharField(max_length=24)
    gross_amount = models.DecimalField(max_digits=10, decimal_places=2)
    gateway_fee = models.DecimalField(max_digits=10, decimal_places=2)
    fee_tax = models.DecimalField(max_digits=10, decimal_places=2)
    net_amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="INR")
    settled_at = models.DateTimeField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(gross_amount__gte=0, gateway_fee__gte=0, fee_tax__gte=0,
            net_amount__gte=0, currency="INR", net_amount=F("gross_amount") - F("gateway_fee") - F("fee_tax")), name="billing_valid_settlement_totals")]


class ReconciliationRecord(FinancialRecord):
    target_kind = models.CharField(max_length=12, choices=[("payment", "Payment"), ("settlement", "Settlement")])
    payment = models.ForeignKey(PaymentTransaction, on_delete=models.PROTECT, null=True, blank=True, related_name="reconciliations")
    settlement = models.ForeignKey(Settlement, on_delete=models.PROTECT, null=True, blank=True, related_name="reconciliations")
    status = models.CharField(max_length=12, choices=[("matched", "Matched"), ("mismatch", "Mismatch"), ("unreconciled", "Unreconciled")])
    expected_amount = models.DecimalField(max_digits=10, decimal_places=2)
    observed_amount = models.DecimalField(max_digits=10, decimal_places=2)
    statement_reference = models.CharField(max_length=128)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.CheckConstraint(condition=Q(target_kind="payment", payment__isnull=False) | Q(target_kind="settlement", payment__isnull=True, settlement__isnull=False), name="billing_reconciliation_target"),
            models.CheckConstraint(condition=Q(expected_amount__gte=0, observed_amount__gte=0, status__in=["matched", "mismatch", "unreconciled"]), name="billing_reconciliation_amounts"),
            models.CheckConstraint(condition=~Q(status="matched") | Q(expected_amount=F("observed_amount")), name="billing_reconciliation_match"),
        ]
