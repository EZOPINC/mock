from unittest.mock import patch

from django.db import OperationalError, connection
from django.test import Client, TestCase
from django.urls import reverse


class FoundationTests(TestCase):
    def test_postgresql_connection(self):
        self.assertEqual(connection.vendor, "postgresql")
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            self.assertEqual(cursor.fetchone(), (1,))

    def test_home(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/home.html")
        self.assertContains(response, "Mock Exam Platform")

    def test_health(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_health_database_failure_does_not_expose_details(self):
        with patch("core.views.connection.cursor", side_effect=OperationalError("private detail")):
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})

    def test_admin_requires_login(self):
        response = self.client.get(reverse("admin:index"))
        self.assertRedirects(response, reverse("admin:login") + "?next=/admin/")

    def test_admin_login_requires_csrf(self):
        response = Client(enforce_csrf_checks=True).post(
            reverse("admin:login"), {"username": "any", "password": "any"}
        )
        self.assertEqual(response.status_code, 403)
