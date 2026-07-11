"""Django settings for transport-service.

transport-service is a stateless resource service: it verifies JWTs issued by
auth-service (via suerp_common) and owns its own transport database. It has no
user model of its own — see services/finance-service/config/settings.py and
services/hostel-service/config/settings.py for the canonical template this
bootstrap mirrors (suerp_common auth/envelope/tenancy, env-driven DB/broker
config, Celery, Prometheus, drf-spectacular). Auth-only bits (AUTH_USER_MODEL,
SIMPLE_JWT, argon2 hashers) are intentionally absent.

Transport-specific: seat availability per BusSchedule is cached in Redis via
Django's cache framework (see CACHES below and transport.services). Tests and
local dev with no live Redis fall back to an in-process LocMemCache.
"""

import sys
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
    "transport",
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
    # Resolves tenant itself (best-effort JWT decode, falling back to
    # subdomain) in its pre-phase, since middleware pre-phases always run
    # before DRF view dispatch/authentication regardless of position in this
    # list — see suerp_common.tenancy.TenantMiddleware docstring.
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
    "TITLE": "SU-ERP Transport Service API",
    "DESCRIPTION": "Routes, stops, bus schedules, seat bookings, and passes for SU-ERP.",
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
# Every service's worker shares the same Redis broker (see REDIS_URL above) —
# without a per-service queue, celery's default "celery" queue collides
# across all services and a worker can pop a task it doesn't recognize
# ("Received unregistered task"), silently discarding it. Pinning each
# service to its own named queue (matched by the "-Q transport" flag on this
# service's celery command in infra/docker-compose.yml) keeps every worker
# only ever consuming its own tasks.
CELERY_TASK_DEFAULT_QUEUE = "transport"

# Drains the transactional outbox (suerp_common.outbox.drain_outbox) every ~5
# seconds so events committed by any view/task get relayed to RabbitMQ with
# low latency. Mirrors the reference services under this service's own domain
# app (transport) and task name.
CELERY_BEAT_SCHEDULE = {
    "drain-outbox-transport": {
        "task": "transport.drain_outbox_task",
        "schedule": 5.0,
    },
}

# --- Cache (seat availability) ---------------------------------------------------
# Seat availability per BusSchedule is cached under a tenant-namespaced key with
# a short TTL (see transport.services). Redis is the real backend, but tests and
# local dev without a live Redis must not require one: when USE_LOCMEM_CACHE is
# set, when running the test suite, or when REDIS_URL is left at its default,
# fall back to an in-process LocMemCache so nothing here needs a running Redis.

_use_locmem = (
    env.bool("USE_LOCMEM_CACHE", default=False) or "test" in sys.argv or "pytest" in sys.modules
)

if _use_locmem:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "transport-locmem",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }

# --- RabbitMQ (event bus) ---------------------------------------------------------
# Read by suerp_common.events via settings.RABBITMQ_URL.

RABBITMQ_URL = env("RABBITMQ_URL", default="amqp://guest:guest@rabbitmq:5672/")
