"""Task: bootstrap_superadmin management command.

A fresh install bootstraps the first platform operator: a `platform`
Institution and a superadmin User inside it. The command is idempotent —
re-running neither duplicates the institution nor the superadmin.
"""

import pytest
from accounts.models import Institution, User
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def _run(**overrides):
    kwargs = {"email": "super@suerp.io", "password": "Str0ngPass!"}
    kwargs.update(overrides)
    call_command("bootstrap_superadmin", **kwargs)


def test_command_creates_platform_institution_and_superadmin():
    _run()

    inst = Institution.objects.get(slug="platform")
    assert inst.name == "Platform"
    assert inst.is_active is True

    superadmin = User.objects.get(tenant=inst, email="super@suerp.io")
    assert superadmin.role == User.Role.SUPERADMIN
    assert superadmin.is_staff is True
    assert superadmin.is_superuser is True
    assert superadmin.check_password("Str0ngPass!") is True


def test_command_is_idempotent_and_does_not_duplicate():
    _run()
    _run()

    assert Institution.objects.filter(slug="platform").count() == 1
    assert User.objects.filter(email="super@suerp.io").count() == 1
