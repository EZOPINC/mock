"""Shared foundation settings. All database access uses PostgreSQL."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ImproperlyConfigured(f"Set the required environment variable {name}.")
    return value


def boolean(name, default="False"):
    value = os.environ.get(name, default).lower()
    if value not in {"true", "false"}:
        raise ImproperlyConfigured(f"{name} must be True or False.")
    return value == "true"


SECRET_KEY = required("DJANGO_SECRET_KEY")
DEBUG = boolean("DJANGO_DEBUG")
ALLOWED_HOSTS = [
    host.strip() for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
    if host.strip()
]
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core.apps.CoreConfig",
    "accounts.apps.AccountsConfig",
    "exams.apps.ExamsConfig",
    "questions.apps.QuestionsConfig",
    "imports.apps.ImportsConfig",
    "previous_year.apps.PreviousYearConfig",
    "general_question.apps.GeneralQuestionConfig",
    "mock_tests.apps.MockTestsConfig",
    "practice.apps.PracticeConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": required("DATABASE_NAME"),
    "USER": required("DATABASE_USER"),
    "PASSWORD": required("DATABASE_PASSWORD"),
    "HOST": required("DATABASE_HOST"),
    "PORT": os.environ.get("DATABASE_PORT", "5432"),
    "OPTIONS": {
        "sslmode": os.environ.get("DATABASE_SSLMODE", "prefer"),
        "connect_timeout": 5,
    },
}}
AUTH_USER_MODEL = "accounts.User"
QUESTION_LANGUAGES = [("en", "English"), ("bn", "Bengali")]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:profile"
LOGOUT_REDIRECT_URL = "home"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
X_FRAME_OPTIONS = "DENY"
IMPORT_STAGING_ROOT = BASE_DIR / ".import-staging"
IMPORT_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
IMPORT_MAX_ROWS = 2000
IMPORT_STAGE_SECONDS = 2 * 60 * 60
