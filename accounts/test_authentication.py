import secrets

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse


class StudentAuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.password = secrets.token_urlsafe(24)
        cls.user = get_user_model().objects.create_user(
            username="student", email="private@example.test", password=cls.password
        )

    def registration_data(self, **overrides):
        password = secrets.token_urlsafe(24)
        return {"username": "newstudent", "email": "new@example.test",
                "password1": password, "password2": password, **overrides}

    def test_register_creates_normal_user_and_session(self):
        data = self.registration_data(is_staff="True", is_superuser="True")
        response = self.client.post(reverse("accounts:register"), data, follow=True)
        user = get_user_model().objects.get(username=data["username"])
        self.assertTrue(user.check_password(data["password1"]))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.assertContains(response, "Your account has been created.")

    def test_duplicate_username_is_rejected(self):
        response = self.client.post(reverse("accounts:register"), self.registration_data(username="STUDENT"))
        self.assertFormError(response.context["form"], "username", "A user with that username already exists.")
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_weak_and_mismatched_passwords_are_rejected(self):
        for first, second in [("123", "123"), ("password", "password"), ("a-long-password-123", "different-password")]:
            with self.subTest(first=first):
                response = self.client.post(reverse("accounts:register"), self.registration_data(password1=first, password2=second))
                self.assertTrue(response.context["form"].errors.get("password2"))
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_invalid_email_is_rejected(self):
        response = self.client.post(reverse("accounts:register"), self.registration_data(email="invalid"))
        self.assertIn("email", response.context["form"].errors)

    def test_login_and_safe_next(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": self.user.username, "password": self.password,
            "next": reverse("mock_tests:index") + "?section=1",
        })
        self.assertRedirects(response, reverse("mock_tests:index") + "?section=1")
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_defaults_to_profile(self):
        response = self.client.post(reverse("accounts:login"), {"username": self.user.username, "password": self.password})
        self.assertRedirects(response, reverse("accounts:profile"))

    def test_invalid_and_inactive_logins_fail(self):
        for inactive in (False, True):
            if inactive:
                self.user.is_active = False
                self.user.save(update_fields=["is_active"])
            response = self.client.post(reverse("accounts:login"), {
                "username": self.user.username, "password": self.password if inactive else "wrong",
            })
            self.assertTrue(response.context["form"].non_field_errors())
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_external_and_malformed_next_are_rejected(self):
        for route in ("accounts:login", "accounts:register"):
            for index, target in enumerate(("https://evil.example/", "//evil.example/", "https:///evil.example", r"/\evil.example", "javascript:alert(1)")):
                with self.subTest(route=route, target=target):
                    self.client.logout()
                    data = ({"username": self.user.username, "password": self.password}
                            if route.endswith("login") else self.registration_data(username=f"new{index}"))
                    response = self.client.post(reverse(route), {**data, "next": target})
                    self.assertRedirects(response, reverse("accounts:profile"))

    def test_https_next_cannot_downgrade_to_http(self):
        response = self.client.post(reverse("accounts:login"), {
            "username": self.user.username, "password": self.password,
            "next": "http://testserver/practice/",
        }, secure=True)
        self.assertEqual(response.url, reverse("accounts:profile"))

    def test_registration_preserves_destination(self):
        target = reverse("practice:index")
        response = self.client.get(reverse("accounts:register"), {"next": target})
        self.assertContains(response, f'name="next" value="{target}"')
        response = self.client.post(reverse("accounts:register"), {**self.registration_data(), "next": target})
        self.assertRedirects(response, target)

    def test_profile_shows_only_current_account(self):
        other = get_user_model().objects.create_user(username="other", email="other@example.test")
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:profile"), {"user": other.pk})
        self.assertContains(response, self.user.username)
        self.assertContains(response, self.user.email)
        self.assertContains(response, "Account created")
        self.assertNotContains(response, other.email)
        self.assertNotContains(response, self.user.password)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_logout_requires_post_and_valid_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.get(reverse("accounts:profile"))
        self.assertEqual(client.get(reverse("accounts:logout")).status_code, 405)
        self.assertEqual(client.post(reverse("accounts:logout")).status_code, 403)
        response = client.post(reverse("accounts:logout"), {
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
            "next": "https://evil.example/",
        })
        self.assertRedirects(response, reverse("home"))
        self.assertNotIn("_auth_user_id", client.session)

    def test_register_and_login_require_csrf_and_accept_valid_tokens(self):
        for route in ("accounts:register", "accounts:login"):
            with self.subTest(route=route):
                client = Client(enforce_csrf_checks=True)
                url = reverse(route)
                self.assertEqual(client.post(url, {}).status_code, 403)
                client.get(url)
                data = (self.registration_data() if route.endswith("register") else
                        {"username": self.user.username, "password": self.password})
                data["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
                response = client.post(url, data)
                self.assertRedirects(response, reverse("accounts:profile"))

    def test_authenticated_registration_does_not_create_another_account(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:register"), self.registration_data())
        self.assertRedirects(response, reverse("accounts:profile"))
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_authenticated_registration_cannot_loop_on_self_next(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:register"), {"next": reverse("accounts:register")})
        self.assertRedirects(response, reverse("accounts:profile"))

    def test_safe_query_next_survives_login_form_and_registration_link(self):
        target = reverse("practice:index") + "?subject=1&topic=2"
        response = self.client.get(reverse("accounts:login"), {"next": target})
        self.assertEqual(response.context["next"], target)
        self.assertContains(response, 'value="/practice/?subject=1&amp;topic=2"')
        self.assertContains(response, '/accounts/register/?next=/practice/%3Fsubject%3D1%26topic%3D2')

    def test_unsafe_query_next_not_rendered_on_authentication_forms(self):
        for route in ("accounts:login", "accounts:register"):
            response = self.client.get(reverse(route), {"next": "https://evil.example/"})
            self.assertEqual(response.context["next"], "")
            self.assertNotContains(response, "evil.example")
