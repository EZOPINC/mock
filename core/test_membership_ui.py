from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from billing.models import SubscriptionPlan


class MembershipPresentationTests(TestCase):
    def test_registration_starts_blank_with_clear_labels(self):
        response = self.client.get(reverse("accounts:register"))
        form = response.context["form"]
        for name in ("username", "email", "password1", "password2"):
            self.assertFalse(form[name].value())
        self.assertContains(response, "Choose a username")
        self.assertContains(response, 'autocomplete="section-register new-password"', count=2)
        self.assertContains(response, "Password requirements")

    def test_public_shell_exposes_membership_from_each_entry_point(self):
        for name in ("home", "accounts:login", "accounts:register", "mock_tests:index",
                     "practice:index", "previous_year:index"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name), follow=True)
                self.assertContains(response, "Get Premium")
                self.assertNotContains(response, 'class="shell-announcement"')
                self.assertNotContains(response, "Your preparation. One place.")
                if name == "home":
                    self.assertContains(response, 'class="foundation-hero"')
                    self.assertContains(response, 'PREPARE WITH PURPOSE')
                    for removed in ('class="shell-announcement"', 'id="home-premium-heading"', 'id="next-step-heading"'):
                        self.assertNotContains(response, removed)
                self.assertContains(response, "Plans &amp; pricing")
                self.assertContains(response, 'href="' + reverse("billing:pricing") + '"')

    @override_settings(BILLING_SIMULATION_ENABLED=False)
    def test_unavailable_purchase_is_explicit(self):
        response = self.client.get(reverse("billing:pricing"))
        self.assertContains(response, "Purchases are currently unavailable")
        self.assertNotContains(response, 'name="checkout_key"')

    @override_settings(BILLING_SIMULATION_ENABLED=True, DEBUG=True,
                       IS_PRODUCTION=False, DJANGO_ENV="dev")
    def test_configured_buy_action_uses_existing_post_checkout(self):
        plan, _ = SubscriptionPlan.objects.update_or_create(code="premium-30", defaults={
            "name": "Monthly Premium", "tier": "premium", "price": "149.00",
            "duration_days": 30, "currency": "INR", "is_active": True})
        self.client.force_login(get_user_model().objects.create_user(username="membership-viewer"))
        response = self.client.get(reverse("billing:pricing"))
        self.assertContains(response, 'method="post" action="' + reverse("billing:checkout", args=[plan.pk]) + '"')
        self.assertContains(response, "Buy Premium")
        self.assertContains(response, "149.00")
        self.assertContains(response, "No real charge")
