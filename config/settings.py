"""Environment-driven dev/prod settings. Database access always uses PostgreSQL."""
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


DJANGO_ENV = os.environ.get("DJANGO_ENV", "dev").strip().lower()
if DJANGO_ENV not in {"dev", "prod"}:
    raise ImproperlyConfigured("DJANGO_ENV must be dev or prod.")
IS_PRODUCTION = DJANGO_ENV == "prod"
SECRET_KEY = required("DJANGO_SECRET_KEY")
DEBUG = boolean("DJANGO_DEBUG")
if IS_PRODUCTION and DEBUG:
    raise ImproperlyConfigured("DJANGO_DEBUG must be False in prod.")
if IS_PRODUCTION:
    required("DJANGO_ALLOWED_HOSTS")
ALLOWED_HOSTS = [
    host.strip() for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
    if host.strip()
]
if IS_PRODUCTION and (not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS):
    raise ImproperlyConfigured("Set explicit DJANGO_ALLOWED_HOSTS in prod; wildcard * is not allowed.")
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
INSTALLED_APPS = [
    "config.admin.PlatformAdminConfig",
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
STATIC_ROOT = Path(os.environ.get("DJANGO_STATIC_ROOT", str(BASE_DIR / "staticfiles")))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = boolean("DJANGO_SECURE_SSL_REDIRECT", "True" if IS_PRODUCTION else "False")
if IS_PRODUCTION and not SECURE_SSL_REDIRECT:
    raise ImproperlyConfigured("DJANGO_SECURE_SSL_REDIRECT must be True in prod.")
# Enable only behind a proxy that strips client-supplied forwarded-proto headers.
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https") if boolean("DJANGO_TRUST_PROXY_HTTPS") else None
)
try:
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0"))
except ValueError as exc:
    raise ImproperlyConfigured("DJANGO_SECURE_HSTS_SECONDS must be a non-negative integer.") from exc
if SECURE_HSTS_SECONDS < 0:
    raise ImproperlyConfigured("DJANGO_SECURE_HSTS_SECONDS must be a non-negative integer.")
X_FRAME_OPTIONS = "DENY"
IMPORT_STAGING_ROOT = Path(os.environ.get("IMPORT_STAGING_ROOT", str(BASE_DIR / ".import-staging")))
IMPORT_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
IMPORT_MAX_ROWS = 2000
IMPORT_STAGE_SECONDS = 2 * 60 * 60
