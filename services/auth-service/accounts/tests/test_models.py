"""Model tests for Task 3.2: Institution (tenant), User, LoginAudit.

Institution is the tenant table itself (not tenant-scoped). User and
LoginAudit belong to a tenant via an explicit FK (not TenantModel — see
accounts/models.py docstring for why auth-service is special).
"""

import pytest
from accounts.models import Institution, LoginAudit, User
from django.db import IntegrityError, transaction

pytestmark = pytest.mark.django_db


def _make_institution(slug="alpha", name="Alpha University"):
    return Institution.objects.create(slug=slug, name=name)


def test_same_email_allowed_across_different_institutions():
    """Two users with the SAME email under DIFFERENT institutions can both
    be created successfully — tenant isolation, not global uniqueness."""
    inst_a = _make_institution(slug="alpha", name="Alpha University")
    inst_b = _make_institution(slug="beta", name="Beta University")

    user_a = User.objects.create_user(
        tenant=inst_a, email="student@example.com", password="s3cur3-pass"
    )
    user_b = User.objects.create_user(
        tenant=inst_b, email="student@example.com", password="s3cur3-pass"
    )

    assert user_a.pk != user_b.pk
    assert user_a.tenant_id == inst_a.id
    assert user_b.tenant_id == inst_b.id


def test_same_email_same_institution_violates_unique_constraint():
    """Creating a second user with the same email under the SAME
    institution raises IntegrityError (unique constraint on tenant+email)."""
    inst = _make_institution()
    User.objects.create_user(tenant=inst, email="dup@example.com", password="s3cur3-pass")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.create_user(tenant=inst, email="dup@example.com", password="another-pass")


def test_create_user_hashes_password():
    """create_user hashes the password: stored value != raw password, and
    check_password(raw) returns True."""
    inst = _make_institution()
    raw_password = "plaintext-password-123"

    user = User.objects.create_user(tenant=inst, email="hash@example.com", password=raw_password)

    assert user.password != raw_password
    assert user.check_password(raw_password) is True


def test_login_audit_allows_null_user_with_email_populated():
    """A LoginAudit row can be created for a failed login where `user` is
    null but `email` is populated (unknown-email lockout counting)."""
    inst = _make_institution()

    audit = LoginAudit.objects.create(
        tenant=inst,
        user=None,
        email="nosuchuser@example.com",
        ip="127.0.0.1",
        success=False,
    )

    assert audit.pk is not None
    assert audit.user is None
    assert audit.email == "nosuchuser@example.com"
    assert audit.success is False
