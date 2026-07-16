"""Django settings for student-service.

Prototype/stub service — a stateless resource service that verifies JWTs
issued by auth-service (via suerp_common) and owns its own student database.
Lean by design: no Celery/Prometheus/OpenAPI wiring (see finance-service for
the full template). Auth-only bits (AUTH_USER_MODEL, SIMPLE_JWT) are absent.
"""

from pathlib import Path

import dj_database_url
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
)
environ.Env.read_env(BASE_DIR / ".env")

# --- Core -------------------------------------------------------------------

SECRET_KEY = env("SECRET_KEY", default="dev-insecure-secret-key-change-me")
DEBUG = env.bool("DEBUG", default=True)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

# Zero-trust JWT: every service verifies signatures itself with this shared
# key. See suerp_common.auth.JWTAuthentication.
JWT_SIGNING_KEY = env("JWT_SIGNING_KEY", default="dev-insecure-change-me")

# Read by suerp_common.events via settings.RABBITMQ_URL (student-consumer's
# manage.py consume_events).
RABBITMQ_URL = env("RABBITMQ_URL", default="amqp://guest:guest@rabbitmq:5672/")

# --- Applications -----------------------------------------------------------

INSTALLED_APPS = [
    "django_prometheus",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "suerp_common",
    "students",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Resolves the active tenant (best-effort JWT decode, subdomain fallback)
    # in its pre-phase, before DRF authentication runs.
    "suerp_common.tenancy.TenantMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ---------------------------------------------------------------
# DATABASE_URL absent -> local sqlite fallback so tests/dev work with zero infra.

_default_sqlite_url = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
DATABASE_URL = env("DATABASE_URL", default=_default_sqlite_url)

DATABASES = {
    "default": dj_database_url.parse(DATABASE_URL),
}

# --- I18n -------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static / misc ----------------------------------------------------------

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Django REST Framework --------------------------------------------------
# Zero-trust JWT auth + uniform response envelope, both from suerp_common.

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "suerp_common.auth.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "EXCEPTION_HANDLER": "suerp_common.envelope.exception_handler",
    "DEFAULT_PAGINATION_CLASS": "suerp_common.envelope.StandardPagination",
    "PAGE_SIZE": 20,
}
