from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AccountSectionTests(TestCase):
    def test_both_sections_require_login(self):
        for name in ("profile", "learning_space"):
            url = reverse(f"accounts:{name}")
            self.assertRedirects(self.client.get(url), reverse("accounts:login") + "?next=" + url)

    def test_profile_only_shows_account_details_and_links_both_sections(self):
        user = get_user_model().objects.create_user(username="student", email="student@example.test")
        self.client.force_login(user)
        with patch("accounts.views.dashboard_context") as dashboard:
            response = self.client.get(reverse("accounts:profile"))
        dashboard.assert_not_called()
        self.assertContains(response, user.email)
        self.assertContains(response, "Account details")
        self.assertNotContains(response, "Recent Mock Tests")
        self.assertNotContains(response, "Recent Practice Sessions")
        self.assertContains(response, reverse("accounts:learning_space"))
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_learning_space_has_dashboard_without_account_details(self):
        user = get_user_model().objects.create_user(username="student", email="student@example.test")
        self.client.force_login(user)
        response = self.client.get(reverse("accounts:learning_space"))
        self.assertContains(response, "Recent Mock Tests")
        self.assertContains(response, "Recent Practice Sessions")
        self.assertNotContains(response, user.email)
        self.assertNotContains(response, "Account details")
        self.assertContains(response, reverse("accounts:profile"))
        self.assertIn("no-store", response.headers["Cache-Control"])
