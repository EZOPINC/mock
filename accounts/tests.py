import secrets

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import User


class UserTests(TestCase):
    def test_custom_user_and_password_hashing(self):
        self.assertIs(get_user_model(), User)
        password = secrets.token_urlsafe(24)
        user = User.objects.create_user(username="learner", password=password)
        self.assertNotEqual(user.password, password)
        self.assertTrue(user.check_password(password))

    def test_admin_login_and_authenticated_session(self):
        password = secrets.token_urlsafe(24)
        admin = User.objects.create_superuser(
            username="administrator", email="admin@example.test", password=password
        )
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("admin:login"))
        response = client.post(reverse("admin:login"), {
            "username": admin.username,
            "password": password,
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
            "next": reverse("admin:index"),
        })
        self.assertRedirects(response, reverse("admin:index"))
        self.assertEqual(int(client.session["_auth_user_id"]), admin.pk)
        self.assertEqual(client.get(reverse("admin:accounts_user_changelist")).status_code, 200)

    def test_nonstaff_user_cannot_access_admin(self):
        user = User.objects.create_user(username="learner")
        self.client.force_login(user)
        response = self.client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("admin:login")))
