"""Explicit Premium context for regressions of the existing random Mock engine."""
from datetime import timedelta
from django.utils import timezone
from billing.models import PlanEntitlement, SubscriptionPlan, UserSubscription


def premium_user(user):
    plan, _ = SubscriptionPlan.objects.get_or_create(code="mock-regression-premium", defaults={
        "name": "Mock regression Premium", "tier": "premium", "price": 0, "duration_days": 30, "is_active": True})
    for feature in PlanEntitlement.Feature.values:
        PlanEntitlement.objects.get_or_create(plan=plan, feature=feature)
    now = timezone.now()
    UserSubscription.objects.create(user=user, plan=plan, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=29))
