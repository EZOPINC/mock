from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class NavigationTests(TestCase):
    def test_public_pages_and_guest_navigation(self):
        for route in ("home", "exams:authorities", "previous_year:index", "accounts:login", "accounts:register"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                for label in ("Home", "Exam Authorities", "Previous Year Questions", "Mock Tests", "Practice Sets", "Login", "Register"):
                    self.assertContains(response, label)
                self.assertNotContains(response, '>Logout<')
                self.assertNotContains(response, '>Profile<')

    def test_protected_routes_preserve_next_with_query(self):
        for route in ("mock_tests:index", "practice:index", "accounts:profile"):
            with self.subTest(route=route):
                destination = reverse(route) + "?page=2"
                response = self.client.get(destination)
                self.assertRedirects(response, reverse("accounts:login") + "?next=" + reverse(route) + "%3Fpage%3D2")

    def test_authenticated_navigation_and_placeholders(self):
        user = get_user_model().objects.create_user(username="learner", email="hidden@example.test")
        self.client.force_login(user)
        for route in ("home", "exams:authorities", "previous_year:index", "mock_tests:index", "practice:index", "accounts:profile"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '>Profile<')
                self.assertContains(response, '>Logout<')
                self.assertNotContains(response, '>Login<')
                self.assertNotContains(response, '>Register<')
                if route != "accounts:profile":
                    self.assertNotContains(response, user.email)
                self.assertContains(response, f'action="{reverse("accounts:logout")}" method="post"')
                self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_home_cards_and_accessible_navigation_markup(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.content.count(b'<article class="module-card">'), 3)
        self.assertContains(response, 'href="#main-content"')
        self.assertContains(response, 'aria-controls="primary-navigation"')
        self.assertContains(response, 'aria-label="Main navigation"')
        self.assertContains(response, 'src="/static/js/navigation.js" defer')

    def test_previous_year_browsing_does_not_offer_test_controls(self):
        response = self.client.get(reverse("previous_year:index"))
        self.assertContains(response, "No published papers are available yet.")
        self.assertNotContains(response, "<select")
