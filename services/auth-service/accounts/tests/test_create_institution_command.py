"""Task: create_institution management command (admin-provisioned onboarding).

The command provisions an Institution and its first admin User atomically,
and is idempotent-ish: re-running with the same slug/admin-email neither
duplicates the institution nor the admin user.
"""

import pytest
from accounts.models import Institution, User
from django.core.management import call_command

pytestmark = pytest.mark.django_db


def _run(**overrides):
    kwargs = {
        "slug": "demo-univ",
        "name": "Demo University",
        "admin_email": "admin@demo.edu",
        "admin_password": "Passw0rd!123",
    }
    kwargs.update(overrides)
    call_command("create_institution", **kwargs)


def test_command_creates_institution_and_admin():
    _run()

    inst = Institution.objects.get(slug="demo-univ")
    assert inst.name == "Demo University"
    assert inst.is_active is True

    admin = User.objects.get(tenant=inst, email="admin@demo.edu")
    assert admin.role == User.Role.ADMIN
    assert admin.check_password("Passw0rd!123") is True


def test_command_is_idempotent_and_does_not_duplicate():
    _run()
    _run()

    assert Institution.objects.filter(slug="demo-univ").count() == 1
    assert User.objects.filter(email="admin@demo.edu").count() == 1
