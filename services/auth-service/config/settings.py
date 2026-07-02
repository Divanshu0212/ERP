"""Django settings for auth-service.

This is the FIRST service in the SU-ERP monorepo and its ``config/`` package is
the template every later Django microservice copies. Anything wired here
(suerp_common auth/envelope/tenancy, env-driven DB/broker config, Celery,
Prometheus, drf-spectacular) should be reproduced identically in the next
service's bootstrap unless that service has a documented reason to diverge.
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

# --- Applications -------------------------------------------------------------

INSTALLED_APPS = [
    "django_prometheus",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "suerp_common",
    "accounts",
]

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Must come after DRF authentication has run (it reads request.tenant_id
    # set by suerp_common.auth.JWTAuthentication), so it sits last among the
    # request-scoped middleware, right before the Prometheus "after" wrapper.
    "suerp_common.tenancy.TenantMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database -----------------------------------------------------------------
# DATABASE_URL absent -> local sqlite fallback so tests/dev work with zero infra.
# READ_DATABASE_URL absent -> read_db mirrors default (read replica ready).

_default_sqlite_url = f"sqlite:///{BASE_DIR / 'db.sqlite3'}"

DATABASE_URL = env("DATABASE_URL", default=_default_sqlite_url)
READ_DATABASE_URL = env("READ_DATABASE_URL", default=DATABASE_URL)

DATABASES = {
    "default": dj_database_url.parse(DATABASE_URL),
    "read_db": dj_database_url.parse(READ_DATABASE_URL),
}

# --- Auth ---------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- I18n -----------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static files ---------------------------------------------------------------

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Django REST Framework ------------------------------------------------------
# Zero-trust JWT auth + uniform response envelope, both from suerp_common — do
# not reinvent these per service.

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
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "SU-ERP Auth Service API",
    "DESCRIPTION": "Authentication, users, roles, and tenant provisioning for SU-ERP.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- Redis / Celery --------------------------------------------------------------

REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# --- RabbitMQ (event bus) ---------------------------------------------------------
# Read by suerp_common.events via settings.RABBITMQ_URL.

RABBITMQ_URL = env("RABBITMQ_URL", default="amqp://guest:guest@rabbitmq:5672/")
