"""Smoke test: the Django project boots and is wired to suerp_common.

This is the bootstrap-level test for Task 3.1. It intentionally does not touch
any models (those arrive in Task 3.2) — it only proves the settings module is
importable, valid, and wired to the shared library as required by the brief.
"""

from django.apps import apps
from django.conf import settings


def test_app_registry_loads():
    """Django's app registry initializes without error."""
    assert apps.apps_ready
    assert apps.get_app_config("accounts").name == "accounts"


def test_jwt_signing_key_is_set():
    """JWT_SIGNING_KEY must come from the environment, per the zero-trust auth
    contract in suerp_common.auth.JWTAuthentication."""
    assert settings.JWT_SIGNING_KEY
    assert isinstance(settings.JWT_SIGNING_KEY, str)


def test_suerp_common_is_installed():
    """suerp_common must be a registered Django app so its OutboxEvent /
    ProcessedEvent models and migrations are picked up."""
    assert "suerp_common" in settings.INSTALLED_APPS
    apps.get_app_config("suerp_common")
