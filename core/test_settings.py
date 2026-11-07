"""Isolated configuration checks; never connect to a production database."""
import os
import runpy
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase


class EnvironmentSettingsTests(SimpleTestCase):
    def load(self, **overrides):
        environment = {
            "DJANGO_SECRET_KEY": "configuration-test-only-key",
            "DATABASE_NAME": "configuration_test",
            "DATABASE_USER": "configuration_test",
            "DATABASE_PASSWORD": "test-only",
            "DATABASE_HOST": "localhost",
        } | overrides
        with patch.dict(os.environ, environment, clear=True), patch("dotenv.load_dotenv"):
            return runpy.run_path(str(Path(__file__).resolve().parents[1] / "config/settings.py"))

    def test_existing_development_environment_still_works(self):
        settings = self.load(DJANGO_DEBUG="True")
        self.assertEqual(settings["DJANGO_ENV"], "dev")
        self.assertTrue(settings["DEBUG"])
        self.assertFalse(settings["SECURE_SSL_REDIRECT"])
        self.assertFalse(settings["SESSION_COOKIE_SECURE"])
        self.assertIsNone(settings["SECURE_PROXY_SSL_HEADER"])
        self.assertEqual(settings["DATABASES"]["default"]["ENGINE"], "django.db.backends.postgresql")

    def test_production_security_and_host_specific_values(self):
        settings = self.load(
            DJANGO_ENV="prod", DJANGO_ALLOWED_HOSTS="exam.example.com, www.exam.example.com",
            DJANGO_CSRF_TRUSTED_ORIGINS="https://exam.example.com",
            DJANGO_TRUST_PROXY_HTTPS="True", DJANGO_SECURE_HSTS_SECONDS="3600",
            DJANGO_STATIC_ROOT="/srv/staticfiles", IMPORT_STAGING_ROOT="/srv/private-staging",
        )
        self.assertFalse(settings["DEBUG"])
        for name in ("SECURE_SSL_REDIRECT", "SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE"):
            self.assertTrue(settings[name])
        self.assertEqual(settings["ALLOWED_HOSTS"], ["exam.example.com", "www.exam.example.com"])
        self.assertEqual(settings["CSRF_TRUSTED_ORIGINS"], ["https://exam.example.com"])
        self.assertEqual(settings["SECURE_PROXY_SSL_HEADER"], ("HTTP_X_FORWARDED_PROTO", "https"))
        self.assertEqual(settings["SECURE_HSTS_SECONDS"], 3600)
        self.assertEqual(settings["STATIC_ROOT"], Path("/srv/staticfiles"))
        self.assertEqual(settings["IMPORT_STAGING_ROOT"], Path("/srv/private-staging"))

    def test_production_rejects_unsafe_configuration(self):
        for overrides in (
            {"DJANGO_DEBUG": "True"}, {"DJANGO_ALLOWED_HOSTS": ""},
            {"DJANGO_ALLOWED_HOSTS": "*"}, {"DJANGO_ALLOWED_HOSTS": ", ,"},
            {"DJANGO_SECURE_SSL_REDIRECT": "False"},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ImproperlyConfigured):
                self.load(**({"DJANGO_ENV": "prod", "DJANGO_ALLOWED_HOSTS": "exam.example.com"} | overrides))

    def test_invalid_environment_and_security_values_fail_clearly(self):
        for overrides in (
            {"DJANGO_ENV": "production-typo"}, {"DJANGO_DEBUG": "yes"},
            {"DJANGO_TRUST_PROXY_HTTPS": "yes"}, {"DJANGO_SECURE_HSTS_SECONDS": "invalid"},
            {"DJANGO_SECURE_HSTS_SECONDS": "-1"},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ImproperlyConfigured):
                self.load(**overrides)

    def test_required_secrets_and_postgresql_values_remain_required(self):
        for name in ("DJANGO_SECRET_KEY", "DATABASE_NAME", "DATABASE_USER", "DATABASE_PASSWORD", "DATABASE_HOST"):
            with self.subTest(name=name), self.assertRaises(ImproperlyConfigured):
                self.load(**{name: ""})
