"""Free allocations. Call inside the start transaction, before selecting questions.

All writers lock the account before reading policy or allowances. Ledger writes
and learning snapshots commit together; Premium never clears or consumes them.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import FreeExamSelection, FreeMockSelection, FreeQuestionUsage, SubscriptionPlan
from .services import plan_for


def _policy(user, feature):
    if not user.is_authenticated or not user.is_active or not user.pk:
        raise ValidationError("An active authenticated account is required.")
    get_user_model().objects.select_for_update().get(pk=user.pk)
    plan = plan_for(user)
    entitlement = plan.entitlements.filter(feature=feature, is_enabled=True).first() if plan else None
    if entitlement is None:
        raise ValidationError("This feature is unavailable on your plan. Premium provides access to all exams.")
    return plan.tier == SubscriptionPlan.Tier.PREMIUM, entitlement


def _select_exam(user, exam_id):
    selection, _ = FreeExamSelection.objects.get_or_create(user=user, defaults={"exam_id": exam_id})
    if selection.exam_id != exam_id:
        raise ValidationError("Your Free exam is already selected. Upgrade to Premium to access other exams. Previous-Year Papers remain free and unlimited.")


@transaction.atomic
def reserve_mock(user, pattern):
    premium, entitlement = _policy(user, "mock")
    if premium:
        return
    if entitlement.usage_limit == 0:
        raise ValidationError("Free Mock access is unavailable. Upgrade to Premium for more Mock Tests.")
    _select_exam(user, pattern.exam_id)
    selection, _ = FreeMockSelection.objects.get_or_create(user=user, defaults={"pattern": pattern})
    if selection.pattern_id != pattern.pk:
        raise ValidationError("Your Free Mock Test set is already selected. Retake that set without limits, or upgrade to Premium for other sets.")


@transaction.atomic
def practice_pool(user, exam_id, candidate_ids, *, sampler):
    """Return eligible revisits plus at most the remaining allowance of new IDs.

    The learning app retains its sampler and all content eligibility rules.
    This pool alone is not a reservation: record_practice must run in the same
    outer account-locked transaction as pool selection and session assembly.
    """
    premium, entitlement = _policy(user, "practice")
    if premium:
        return set(candidate_ids), False
    _select_exam(user, exam_id)
    used_ids = set(FreeQuestionUsage.objects.filter(user=user).values_list("question_id", flat=True))
    revisits = set(candidate_ids) & used_ids
    new = set(candidate_ids) - used_ids
    remaining = len(new) if entitlement.usage_limit is None else max(0, entitlement.usage_limit - len(used_ids))
    if len(new) > remaining:
        new = set(sampler.sample(sorted(new), remaining))
    return revisits | new, True


def record_practice(user, question_ids):
    """Persist distinct Free deliveries under the caller's account lock."""
    existing = set(FreeQuestionUsage.objects.filter(user=user, question_id__in=question_ids).values_list("question_id", flat=True))
    FreeQuestionUsage.objects.bulk_create([
        FreeQuestionUsage(user=user, question_id=pk) for pk in set(question_ids) - existing
    ])
