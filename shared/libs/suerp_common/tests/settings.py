"""Minimal Django settings for exercising suerp_common in isolation."""

SECRET_KEY = "test-only-secret"
JWT_SIGNING_KEY = "test-jwt-key"
DEBUG = True

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "suerp_common",
    "tests.testapp",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

MIDDLEWARE = [
    "suerp_common.tenancy.TenantMiddleware",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["suerp_common.auth.JWTAuthentication"],
    "EXCEPTION_HANDLER": "suerp_common.envelope.exception_handler",
    "DEFAULT_PAGINATION_CLASS": "suerp_common.envelope.StandardPagination",
    "PAGE_SIZE": 20,
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
