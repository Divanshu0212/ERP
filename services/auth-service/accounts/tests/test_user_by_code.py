"""GET /auth/users/by-code/ — resolve a user_code to its User row within the
caller's own tenant. Every student_user_code/warden_id in this platform IS
this user_code (see docs/superpowers/specs/2026-07-07-user-code-profile-design.md),
so this single endpoint is the whole identity-resolution story for
hostel-service's user_code-based allocation and block-creation flows.
"""

import pytest
from accounts.models import Institution, User
from rest_framework.test import APIClient


@pytest.fixture
def institution(db):
    return Institution.objects.create(slug="code-lookup", name="Code Lookup U")


@pytest.fixture
def admin_user(db, institution):
    return User.objects.create_user(
        tenant=institution,
        email="admin@codelookup.edu",
        password="pw12345678",
        role=User.Role.ADMIN,
        user_code="ADM-001",
    )


def _login(client, institution, email, password):
    resp = client.post(
        "/api/v1/auth/login",
        {"institution_slug": institution.slug, "email": email, "password": password},
        format="json",
    )
    return resp.json()["data"]["access"]


def test_resolve_by_code_success(db, institution, admin_user):
    client = APIClient()
    token = _login(client, institution, "admin@codelookup.edu", "pw12345678")
    User.objects.create_user(
        tenant=institution,
        email="stu@codelookup.edu",
        password="pw12345678",
        role=User.Role.STUDENT,
        user_code="STU-777",
    )
    resp = client.get(
        "/api/v1/auth/users/by-code/",
        {"user_code": "STU-777"},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["user_code"] == "STU-777"
    assert body["data"]["email"] == "stu@codelookup.edu"


def test_resolve_by_code_not_found(db, institution, admin_user):
    client = APIClient()
    token = _login(client, institution, "admin@codelookup.edu", "pw12345678")
    resp = client.get(
        "/api/v1/auth/users/by-code/",
        {"user_code": "NOPE-999"},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 404


def test_resolve_by_code_requires_query_param(db, institution, admin_user):
    client = APIClient()
    token = _login(client, institution, "admin@codelookup.edu", "pw12345678")
    resp = client.get(
        "/api/v1/auth/users/by-code/",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 400


def test_resolve_by_code_is_tenant_scoped(db, institution, admin_user):
    other_institution = Institution.objects.create(slug="other-code-lookup", name="Other U")
    User.objects.create_user(
        tenant=other_institution,
        email="stu@othercodelookup.edu",
        password="pw12345678",
        role=User.Role.STUDENT,
        user_code="STU-777",
    )
    client = APIClient()
    token = _login(client, institution, "admin@codelookup.edu", "pw12345678")
    resp = client.get(
        "/api/v1/auth/users/by-code/",
        {"user_code": "STU-777"},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 404


def test_resolve_by_code_forbidden_for_student(db, institution, admin_user):
    User.objects.create_user(
        tenant=institution,
        email="stu@codelookup.edu",
        password="pw12345678",
        role=User.Role.STUDENT,
        user_code="STU-777",
    )
    client = APIClient()
    token = _login(client, institution, "stu@codelookup.edu", "pw12345678")
    resp = client.get(
        "/api/v1/auth/users/by-code/",
        {"user_code": "STU-777"},
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert resp.status_code == 403
