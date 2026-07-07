"""Task: create_institution management command (admin-provisioned onboarding).

The command provisions an Institution and its first admin User atomically,
and is idempotent-ish: re-running with the same slug/admin-email neither
duplicates the institution nor the admin user.
"""

import pytest
from accounts.models import Institution, User
from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = pytest.mark.django_db


def _run(**overrides):
    kwargs = {
        "slug": "demo-univ",
        "name": "Demo University",
        "admin_email": "admin@demo.edu",
        "admin_password": "Passw0rd!123",
        "admin_user_code": "ADM-DEMO-001",
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


def test_create_institution_requires_admin_user_code(db):
    with pytest.raises(CommandError):
        call_command(
            "create_institution",
            slug="no-code-univ",
            name="No Code University",
            admin_email="admin@nocode.edu",
            admin_password="Passw0rd!123",
        )


def test_create_institution_with_admin_user_code(db):
    call_command(
        "create_institution",
        slug="coded-univ",
        name="Coded University",
        admin_email="admin@coded.edu",
        admin_password="Passw0rd!123",
        admin_user_code="ADM-CODED-001",
    )
    user = User.objects.get(user_code="ADM-CODED-001")
    assert user.email == "admin@coded.edu"
    assert user.role == User.Role.ADMIN
