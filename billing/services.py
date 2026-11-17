"""Read-only billing policy. Content eligibility remains owned by each learning app."""
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.db.models import Q

from .models import PlanEntitlement, SubscriptionPlan, UserSubscription


def subscription_for(user, *, at=None):
    """Effective Premium, independent of exam. Latest-starting overlapping term wins."""
    if not user.is_authenticated or not user.is_active or not user.pk:
        return None
    at = at if at is not None else timezone.now()
    return (UserSubscription.objects.select_related("plan").filter(
        user=user, status=UserSubscription.Status.ACTIVE, starts_at__lte=at,
        ends_at__gt=at, plan__tier=SubscriptionPlan.Tier.PREMIUM,
    ).filter(Q(plan__is_active=True) | Q(plan_snapshot__source="lifecycle")).order_by("-starts_at", "-pk").first())


def plan_for(user, *, at=None):
    subscription = subscription_for(user, at=at)
    return subscription.plan if subscription else SubscriptionPlan.objects.filter(
        tier=SubscriptionPlan.Tier.FREE, is_active=True).first()


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str
    plan_code: str | None = None
    usage_limit: int | None = None
    usage_period: str | None = None


def evaluate_access(user, feature, *, used=0, requested=1, at=None):
    """Evaluate units supplied by a trusted caller for the configured usage period.

    This does not count/reserve usage or grant content eligibility. Enforcement and
    atomic metering at learning workflow boundaries are deliberately outside B1.
    """
    if feature not in PlanEntitlement.Feature.values:
        raise ValueError("Unknown billing feature.")
    if type(used) is not int or used < 0 or type(requested) is not int or requested < 1:
        raise ValueError("Usage must be a nonnegative integer and requested units a positive integer.")
    if not user.is_authenticated or not user.is_active or not user.pk:
        return AccessDecision(False, "active_account_required")
    plan = plan_for(user, at=at)
    if plan is None:
        return AccessDecision(False, "plan_unavailable")
    entitlement = plan.entitlements.filter(feature=feature).first()
    if entitlement is None or not entitlement.is_enabled:
        return AccessDecision(False, "feature_disabled", plan.code)
    allowed = entitlement.usage_limit is None or used + requested <= entitlement.usage_limit
    return AccessDecision(allowed, "allowed" if allowed else "usage_limit_reached", plan.code,
                          entitlement.usage_limit, entitlement.usage_period)


def mock_access(user, **kwargs):
    return evaluate_access(user, PlanEntitlement.Feature.MOCK, **kwargs)


def practice_access(user, **kwargs):
    return evaluate_access(user, PlanEntitlement.Feature.PRACTICE, **kwargs)


def revision_access(user, **kwargs):
    return evaluate_access(user, PlanEntitlement.Feature.REVISION, **kwargs)


def require_access(user, feature, **kwargs):
    decision = evaluate_access(user, feature, **kwargs)
    if not decision.allowed:
        raise PermissionDenied(decision.reason)
    return decision
