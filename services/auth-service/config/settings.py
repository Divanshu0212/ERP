"""Django settings for auth-service.

This is the FIRST service in the SU-ERP monorepo and its ``config/`` package is
the template every later Django microservice copies. Anything wired here
(suerp_common auth/envelope/tenancy, env-driven DB/broker config, Celery,
Prometheus, drf-spectacular) should be reproduced identically in the next
service's bootstrap unless that service has a documented reason to diverge.
"""

from datetime import timedelta
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

# --- Auth ---------------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

# Argon2 first: strongest available hasher becomes the default for new
# password hashes. Django still recognizes/upgrades legacy hashes with the
# others listed here.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# accounts.User.email (USERNAME_FIELD) is deliberately unique per-tenant
# (tenant, email) rather than globally unique — the same email can belong to
# a different person at a different institution. Stock ModelBackend does a
# global `.get(email=...)` lookup, which would authenticate against the wrong
# tenant's user, so TenantAuthBackend (accounts/backends.py) scopes the
# lookup to (tenant, email) instead. Declaring a non-default backend here
# downgrades Django's auth.E003 check to a harmless warning (it no longer
# assumes stock ModelBackend semantics apply), so the check no longer needs
# silencing.
#
# Deliberately NOT also listing ModelBackend here: it would run as a fallback
# whenever TenantAuthBackend returns None, doing a *global* `.get(email=...)`
# lookup keyed only on USERNAME_FIELD — exactly the cross-tenant leak this
# backend exists to prevent (and it raises MultipleObjectsReturned outright
# once the same email exists at two institutions).
AUTHENTICATION_BACKENDS = [
    "accounts.backends.TenantAuthBackend",
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

# --- SimpleJWT ------------------------------------------------------------------
# accounts.views issues tokens manually (RefreshToken.for_user + explicit
# claim assignment) rather than via SimpleJWT's default TokenObtainPairView,
# so most of these only govern signing/lifetime and the /refresh endpoint.
# USER_ID_CLAIM/USER_ID_FIELD make the "sub" claim carry the user's pk —
# the exact claim key suerp_common.auth.JWTAuthentication reads on every
# other service. User.user_code is now the literal primary key (replacing
# the old UUID id — see accounts/models.py), so RefreshToken.for_user(user)
# (called from accounts.views._issue_tokens) reads it via this field name.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": JWT_SIGNING_KEY,
    "USER_ID_FIELD": "user_code",
    "USER_ID_CLAIM": "sub",
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
# service to its own named queue (matched by the "-Q auth" flag on this
# service's celery command in infra/docker-compose.yml) keeps every worker
# only ever consuming its own tasks.
CELERY_TASK_DEFAULT_QUEUE = "auth"

# Drains the transactional outbox (suerp_common.outbox.drain_outbox) every ~5
# seconds so events committed by any view/task get relayed to RabbitMQ with
# low latency. Every later service wires its own accounts/domain app's
# drain_outbox_task the same way under its own beat schedule name.
CELERY_BEAT_SCHEDULE = {
    "drain-outbox": {
        "task": "accounts.drain_outbox_task",
        "schedule": 5.0,
    },
}

# --- RabbitMQ (event bus) ---------------------------------------------------------
# Read by suerp_common.events via settings.RABBITMQ_URL.

RABBITMQ_URL = env("RABBITMQ_URL", default="amqp://guest:guest@rabbitmq:5672/")
