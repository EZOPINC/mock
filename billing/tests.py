from datetime import timedelta
from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase
from django.utils import timezone

from .models import PlanEntitlement, SubscriptionPlan, UserSubscription
from .services import (evaluate_access, mock_access, plan_for, practice_access,
                       require_access, revision_access, subscription_for)


class BillingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="billing-student")
        cls.free = SubscriptionPlan.objects.get(code="free")
        cls.premium = SubscriptionPlan.objects.get(code="premium-30")
        cls.premium.is_active = True
        cls.premium.price = Decimal("149.00")
        cls.premium.save()

    def subscribe(self, **overrides):
        now = timezone.now()
        values = dict(user=self.user, plan=self.premium, starts_at=now - timedelta(days=1),
                      ends_at=now + timedelta(days=29))
        values.update(overrides)
        return UserSubscription.objects.create(**values)

    def test_seeded_configuration(self):
        self.assertEqual(SubscriptionPlan.objects.count(), 4)
        self.assertEqual(PlanEntitlement.objects.count(), 12)
        self.assertFalse(SubscriptionPlan.objects.get(code="premium-90").is_active)
        self.assertEqual(set(SubscriptionPlan.objects.filter(tier="premium").values_list("duration_days", flat=True)), {30, 90, 365})

    def test_free_fallback_does_not_create_subscription(self):
        self.assertEqual(plan_for(self.user), self.free)
        for access in (mock_access, practice_access, revision_access):
            self.assertTrue(access(self.user).allowed)
        self.assertFalse(UserSubscription.objects.exists())

    def test_premium_replaces_free_for_all_features_without_exam_scope(self):
        self.subscribe()
        self.free.entitlements.update(is_enabled=False)
        for access in (mock_access, practice_access, revision_access):
            self.assertEqual(access(self.user).plan_code, self.premium.code)
            self.assertTrue(access(self.user).allowed)

    def test_term_boundaries(self):
        subscription = self.subscribe()
        self.assertEqual(plan_for(self.user, at=subscription.starts_at), self.premium)
        self.assertEqual(plan_for(self.user, at=subscription.starts_at - timedelta(microseconds=1)), self.free)
        self.assertEqual(plan_for(self.user, at=subscription.ends_at), self.free)

    def test_cancelled_and_inactive_plan_fall_back(self):
        sub = self.subscribe(status="cancelled")
        self.assertEqual(plan_for(self.user), self.free)
        sub.status = "active"
        sub.save()
        self.premium.is_active = False
        self.premium.save()
        self.assertEqual(plan_for(self.user), self.free)

    def test_other_users_subscription_does_not_grant_premium(self):
        other = get_user_model().objects.create_user(username="other")
        self.subscribe(user=other)
        self.assertEqual(plan_for(self.user), self.free)

    def test_overlap_resolution_is_deterministic(self):
        old = self.subscribe()
        new = self.subscribe(starts_at=old.starts_at + timedelta(hours=1))
        self.assertEqual(subscription_for(self.user), new)

    def test_missing_or_disabled_entitlement_denies_without_free_merge(self):
        self.subscribe()
        self.premium.entitlements.filter(feature="mock").delete()
        self.assertEqual(mock_access(self.user).reason, "feature_disabled")
        self.premium.entitlements.filter(feature="practice").update(is_enabled=False)
        self.assertFalse(practice_access(self.user).allowed)

    def test_limits_zero_boundary_and_unlimited(self):
        entitlement = self.free.entitlements.get(feature="mock")
        entitlement.usage_limit = 3
        entitlement.usage_period = "day"
        entitlement.save()
        self.assertTrue(mock_access(self.user, used=2).allowed)
        decision = mock_access(self.user, used=2, requested=2)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.usage_period, "day")
        entitlement.usage_limit = 0
        entitlement.save()
        self.assertFalse(mock_access(self.user).allowed)
        entitlement.usage_limit = None
        entitlement.save()
        self.assertTrue(mock_access(self.user, used=100000).allowed)

    def test_missing_or_inactive_free_fails_closed(self):
        self.free.is_active = False
        self.free.save()
        self.assertEqual(mock_access(self.user).reason, "plan_unavailable")
        self.free.delete()
        self.assertFalse(mock_access(self.user).allowed)

    def test_inactive_and_anonymous_users_denied_even_with_subscription(self):
        self.subscribe()
        self.user.is_active = False
        self.assertFalse(mock_access(self.user).allowed)
        self.assertFalse(mock_access(AnonymousUser()).allowed)

    def test_invalid_usage_or_feature_rejected(self):
        for kwargs in ({"used": -1}, {"requested": 0}, {"used": True}, {"requested": 1.5}):
            with self.assertRaises(ValueError):
                mock_access(self.user, **kwargs)
        with self.assertRaises(ValueError):
            evaluate_access(self.user, "unknown")

    def test_require_access_raises_permission_denied(self):
        self.free.entitlements.filter(feature="revision").update(is_enabled=False)
        with self.assertRaises(PermissionDenied):
            require_access(self.user, "revision")

    def test_plan_validation_and_database_guards(self):
        for changes in ({"price": -1}, {"duration_days": 15}, {"currency": "USD"}):
            plan = SubscriptionPlan.objects.get(pk=self.premium.pk)
            for key, value in changes.items():
                setattr(plan, key, value)
            with self.assertRaises(ValidationError):
                plan.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SubscriptionPlan.objects.filter(pk=self.premium.pk).update(duration_days=None)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SubscriptionPlan.objects.create(code="another-free", name="Free", tier="free", price=0)

    def test_subscription_validation_and_database_guard(self):
        with self.assertRaises(ValidationError):
            self.subscribe(plan=self.free)
        with self.assertRaises(ValidationError):
            self.subscribe(ends_at=timezone.now() - timedelta(days=2))
        sub = self.subscribe()
        with self.assertRaises(IntegrityError), transaction.atomic():
            UserSubscription.objects.filter(pk=sub.pk).update(ends_at=sub.starts_at)

    def test_plan_edits_preserve_recorded_subscription_term(self):
        sub = self.subscribe()
        self.premium.duration_days = 90
        self.premium.save()
        sub.refresh_from_db()
        self.assertEqual(sub.ends_at - sub.starts_at, timedelta(days=30))

    def test_entitlement_uniqueness_and_free_period(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PlanEntitlement.objects.create(plan=self.free, feature="mock")
        entitlement = self.free.entitlements.get(feature="mock")
        entitlement.usage_period = "subscription"
        with self.assertRaises(ValidationError):
            entitlement.full_clean()

    def test_admin_requires_explicit_model_permissions(self):
        staff = get_user_model().objects.create_user(username="billing-staff", is_staff=True)
        request = RequestFactory().get("/admin/")
        request.user = staff
        for model in (SubscriptionPlan, PlanEntitlement, UserSubscription):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_view_permission(request))
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
        staff.user_permissions.add(Permission.objects.get(codename="view_subscriptionplan"))
        request.user = get_user_model().objects.get(pk=staff.pk)
        self.assertTrue(admin.site._registry[SubscriptionPlan].has_view_permission(request))
        self.assertFalse(admin.site._registry[SubscriptionPlan].has_change_permission(request))
