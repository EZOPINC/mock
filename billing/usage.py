"""Free allocations. Call inside the start transaction, before selecting questions.

All writers lock the account before reading policy or allowances. Ledger writes
and learning snapshots commit together; Premium never clears or consumes them.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import FreeExamSelection, FreeQuestionUsage, SubscriptionPlan
from .services import plan_for


PRACTICE_UPGRADE_MESSAGE = "Your Free Practice allowance cannot provide new questions for this selection. Revisit previously delivered questions, choose a smaller set, or upgrade to Premium for unlimited Practice."


def _policy(user, feature):
    if not user.is_authenticated or not user.is_active or not user.pk:
        raise ValidationError("An active authenticated account is required.")
    owner = get_user_model().objects.select_for_update().get(pk=user.pk)
    if not owner.is_active:
        raise ValidationError("An active authenticated account is required.")
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
        return False
    if entitlement.usage_limit == 0:
        raise ValidationError("Free Mock access is unavailable. Upgrade to Premium for more Mock Tests.")
    _select_exam(user, pattern.exam_id)
    if not pattern.is_active or not pattern.is_free_demo or not pattern.has_frozen_set:
        raise ValidationError("Free access is limited to this exam's published shared Free Demo; upgrade to Premium for other Mock Tests.")
    # Legacy per-user Mock selections are retained for audit/history, but no
    # longer choose or restrict the shared demo. Exam selection still persists.
    return True


@transaction.atomic
def practice_pool(user, exam_id, candidate_ids, *, sampler, session_size=None):
    """Bound the eligible pool by lifetime allowance and optional batch size.

    Batches prefer unseen masters, then eligible revisits only if the scope ran
    out of unseen content without exhausting quota. No new-question capacity
    raises the existing upgrade prompt; an allocated-only scope is revisitable.

    The learning app retains its sampler and all content eligibility rules.
    This pool alone is not a reservation: record_practice must run in the same
    outer account-locked transaction as pool selection and session assembly.
    """
    premium, entitlement = _policy(user, "practice")
    if premium:
        return set(candidate_ids), False
    _select_exam(user, exam_id)
    usage = FreeQuestionUsage.objects.filter(user=user)
    revisits = set(usage.filter(question_id__in=candidate_ids).values_list("question_id", flat=True))
    new = set(candidate_ids) - revisits
    remaining = len(new) if entitlement.usage_limit is None else max(0, entitlement.usage_limit - usage.count())
    if session_size is not None:
        if type(session_size) is not int or session_size <= 0:
            raise ValueError("Practice session size must be a positive integer.")
        if new:
            if not remaining:
                raise ValidationError(PRACTICE_UPGRADE_MESSAGE)
            quota_limited = remaining < len(new)
            # Prioritize unseen masters. A quota-limited final batch consumes
            # only the remaining slots rather than filling from old questions.
            new = set(sampler.sample(sorted(new), min(session_size, remaining, len(new))))
            # Small language/taxonomy scopes can include allocated questions.
            # Fill from those only when the scope, rather than lifetime quota,
            # ran out of unseen questions; never displace an eligible new unit.
            if not quota_limited and len(new) < session_size:
                new |= set(sampler.sample(sorted(revisits), min(session_size - len(new), len(revisits))))
            return new, True
        return set(sampler.sample(sorted(revisits), min(session_size, len(revisits)))), True
    if len(new) > remaining:
        new = set(sampler.sample(sorted(new), remaining))
    return revisits | new, True


def record_practice(user, question_ids):
    """Persist distinct Free deliveries under the caller's account lock."""
    existing = set(FreeQuestionUsage.objects.filter(user=user, question_id__in=question_ids).values_list("question_id", flat=True))
    FreeQuestionUsage.objects.bulk_create([
        FreeQuestionUsage(user=user, question_id=pk) for pk in set(question_ids) - existing
    ])
