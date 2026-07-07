"""Model tests for Task 3.2: Institution (tenant), User, LoginAudit.

Institution is the tenant table itself (not tenant-scoped). User and
LoginAudit belong to a tenant via an explicit FK (not TenantModel — see
accounts/models.py docstring for why auth-service is special).
"""

import pytest
from accounts.models import Institution, LoginAudit, User, UserProfile
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
        tenant=inst_a, email="student@example.com", password="s3cur3-pass", user_code="A-001"
    )
    user_b = User.objects.create_user(
        tenant=inst_b, email="student@example.com", password="s3cur3-pass", user_code="B-001"
    )

    assert user_a.pk != user_b.pk
    assert user_a.tenant_id == inst_a.id
    assert user_b.tenant_id == inst_b.id


def test_same_email_same_institution_violates_unique_constraint():
    """Creating a second user with the same email under the SAME
    institution raises IntegrityError (unique constraint on tenant+email)."""
    inst = _make_institution()
    User.objects.create_user(
        tenant=inst, email="dup@example.com", password="s3cur3-pass", user_code="DUP-001"
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.create_user(
                tenant=inst,
                email="dup@example.com",
                password="another-pass",
                user_code="DUP-002",
            )


def test_create_user_hashes_password():
    """create_user hashes the password: stored value != raw password, and
    check_password(raw) returns True."""
    inst = _make_institution()
    raw_password = "plaintext-password-123"

    user = User.objects.create_user(
        tenant=inst, email="hash@example.com", password=raw_password, user_code="HASH-001"
    )

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


def test_user_code_is_primary_key():
    """user_code is the literal primary key of User, not an auto id."""
    institution = _make_institution(slug="test-uc", name="Test UC")
    user = User.objects.create_user(
        tenant=institution,
        email="a@test.com",
        password="pw12345678",
        role=User.Role.STUDENT,
        user_code="STU-001",
    )
    assert user.pk == "STU-001"
    assert User.objects.get(pk="STU-001").email == "a@test.com"


def test_user_code_unique_per_tenant():
    """user_code must be unique within a tenant.

    Deviation from the design spec, documented in accounts/models.py's module
    docstring: the spec also wanted the SAME user_code reusable across
    DIFFERENT tenants, but that is incompatible with user_code being a
    single-column primary key (a PRIMARY KEY is necessarily globally unique
    on every backend — verified directly against Postgres). Since decision 1
    ("literal PK swap", `user.pk == "STU-001"`) is load-bearing for every
    other migration task, this test asserts the achievable half: uniqueness
    holds globally, which is a strict superset of "unique per tenant."
    """
    inst_a = _make_institution(slug="uc-a", name="UC A")
    inst_b = _make_institution(slug="uc-b", name="UC B")
    User.objects.create_user(
        tenant=inst_a,
        email="a@test.com",
        password="pw12345678",
        role=User.Role.STUDENT,
        user_code="STU-001",
    )
    # Same user_code in a DIFFERENT tenant is ALSO rejected (global
    # uniqueness, since user_code is a single-column primary key).
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.create_user(
                tenant=inst_b,
                email="b@test.com",
                password="pw12345678",
                role=User.Role.STUDENT,
                user_code="STU-001",
            )
    # Same user_code in the SAME tenant is rejected too.
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.create_user(
                tenant=inst_a,
                email="c@test.com",
                password="pw12345678",
                role=User.Role.STUDENT,
                user_code="STU-001",
            )


def test_superadmin_has_no_user_code():
    """Superadmin is excluded from the admin-assigned user_code scheme.

    Note: the pk column itself can never be NULL (a SQL PRIMARY KEY always
    implies NOT NULL — verified against Postgres; see accounts/models.py
    module docstring for the full explanation). Superadmin still gets a
    non-null pk value under the hood (a system-generated placeholder), but
    `has_user_code` is False, meaning nothing admin-assigned or
    admin-visible was ever set for this row.
    """
    institution = _make_institution(slug="platform-test", name="Platform")
    user = User.objects.create_superuser(
        tenant=institution,
        email="root@test.com",
        password="pw12345678",
        role=User.Role.SUPERADMIN,
    )
    assert user.has_user_code is False
    assert user.user_code is not None  # real pk value always exists


def test_user_profile_one_to_one():
    """UserProfile is 1:1 with User, keyed off the same user_code as its pk."""
    institution = _make_institution(slug="test-up", name="Test UP")
    user = User.objects.create_user(
        tenant=institution,
        email="a@test.com",
        password="pw12345678",
        role=User.Role.STUDENT,
        user_code="STU-002",
    )
    profile = UserProfile.objects.create(user=user, phone="9999999999", gender="female")
    assert profile.pk == "STU-002"
    assert user.profile.phone == "9999999999"
