"""Task: institution detail + admin-driven user management.

Covers:
- GET /auth/institution  -> caller's institution (any authenticated user),
  resolved from the tenant claim (cross-tenant isolation).
- GET /auth/users        -> admin-only, tenant-scoped user list.
- POST /auth/users       -> admin creates a user in their own institution,
  emits exactly one user.registered outbox event, and never trusts a tenant
  supplied in the body.
"""

import pytest
from accounts.models import Institution, User
from rest_framework.test import APIClient
from suerp_common.outbox import OutboxEvent

pytestmark = pytest.mark.django_db


def _make_institution(slug="alpha", name="Alpha University", is_active=True):
    return Institution.objects.create(slug=slug, name=name, is_active=is_active)


@pytest.fixture
def client():
    return APIClient()


def _register(client, institution, email, password="s3cur3-passw0rd", role=None):
    payload = {
        "institution_slug": institution.slug,
        "email": email,
        "password": password,
    }
    if role is not None:
        payload["role"] = role
    return client.post("/api/v1/auth/register", payload, format="json")


def _token(client, institution, email, password="s3cur3-passw0rd"):
    resp = client.post(
        "/api/v1/auth/login",
        {"institution_slug": institution.slug, "email": email, "password": password},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    return resp.json()["data"]["access"]


def _admin_token(client, institution, email="admin@example.com"):
    _register(client, institution, email=email, role=User.Role.ADMIN)
    return _token(client, institution, email)


# --- GET /auth/institution -------------------------------------------------


def test_institution_detail_returns_callers_institution(client):
    inst = _make_institution()
    token = _admin_token(client, inst)

    resp = client.get("/api/v1/auth/institution", HTTP_AUTHORIZATION=f"Bearer {token}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert data["id"] == str(inst.id)
    assert data["slug"] == inst.slug
    assert data["name"] == inst.name
    assert data["is_active"] is True
    assert "created_at" in data


def test_institution_detail_requires_authentication(client):
    resp = client.get("/api/v1/auth/institution")
    assert resp.status_code == 401


def test_institution_detail_is_isolated_per_tenant(client):
    _make_institution(slug="alpha", name="Alpha University")  # another tenant exists
    inst_b = _make_institution(slug="beta", name="Beta University")

    token_b = _admin_token(client, inst_b, email="admin@beta.example.com")
    resp = client.get("/api/v1/auth/institution", HTTP_AUTHORIZATION=f"Bearer {token_b}")

    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == str(inst_b.id)
    assert resp.json()["data"]["slug"] == "beta"


# --- GET /auth/users -------------------------------------------------------


def test_list_users_as_admin_returns_only_same_tenant_users(client):
    inst_a = _make_institution(slug="alpha", name="Alpha University")
    inst_b = _make_institution(slug="beta", name="Beta University")

    admin_token = _admin_token(client, inst_a)
    _register(client, inst_a, email="student@alpha.example.com", role=User.Role.STUDENT)
    _register(client, inst_b, email="student@beta.example.com", role=User.Role.STUDENT)

    resp = client.get("/api/v1/auth/users", HTTP_AUTHORIZATION=f"Bearer {admin_token}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    results = body["data"]["results"]
    emails = {u["email"] for u in results}
    assert emails == {"admin@example.com", "student@alpha.example.com"}
    for user in results:
        assert set(user.keys()) == {"id", "email", "role", "is_active", "date_joined"}


def test_list_users_forbidden_for_student(client):
    inst = _make_institution()
    _register(client, inst, email="student@example.com", role=User.Role.STUDENT)
    token = _token(client, inst, "student@example.com")

    resp = client.get("/api/v1/auth/users", HTTP_AUTHORIZATION=f"Bearer {token}")

    assert resp.status_code == 403


def test_list_users_requires_authentication(client):
    resp = client.get("/api/v1/auth/users")
    assert resp.status_code == 401


# --- POST /auth/users ------------------------------------------------------


def test_admin_creates_user_and_emits_one_event(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)

    resp = client.post(
        "/api/v1/auth/users",
        {"email": "faculty@example.com", "role": User.Role.FACULTY, "password": "n3w-passw0rd"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["email"] == "faculty@example.com"
    assert data["role"] == User.Role.FACULTY

    user = User.objects.get(tenant=inst, email="faculty@example.com")
    assert data["id"] == str(user.id)
    assert user.check_password("n3w-passw0rd") is True

    events = OutboxEvent.objects.filter(type="user.registered", payload__user_id=str(user.id))
    assert events.count() == 1
    assert events.first().payload["role"] == User.Role.FACULTY


def test_admin_created_user_belongs_to_admins_tenant_even_if_body_lies(client):
    inst_a = _make_institution(slug="alpha", name="Alpha University")
    inst_b = _make_institution(slug="beta", name="Beta University")
    admin_token = _admin_token(client, inst_a)

    resp = client.post(
        "/api/v1/auth/users",
        {
            "email": "mole@example.com",
            "role": User.Role.STUDENT,
            "password": "n3w-passw0rd",
            "tenant": str(inst_b.id),
            "tenant_id": str(inst_b.id),
            "institution_slug": inst_b.slug,
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 201, resp.content
    assert User.objects.filter(tenant=inst_a, email="mole@example.com").exists()
    assert not User.objects.filter(tenant=inst_b, email="mole@example.com").exists()


def test_admin_create_user_rejects_duplicate_email_in_tenant(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)
    _register(client, inst, email="dupe@example.com", role=User.Role.STUDENT)

    resp = client.post(
        "/api/v1/auth/users",
        {"email": "dupe@example.com", "role": User.Role.STUDENT, "password": "n3w-passw0rd"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_admin_create_user_rejects_invalid_role(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)

    resp = client.post(
        "/api/v1/auth/users",
        {"email": "who@example.com", "role": "overlord", "password": "n3w-passw0rd"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert not User.objects.filter(email="who@example.com").exists()


def test_admin_create_user_rejects_short_password(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)

    resp = client.post(
        "/api/v1/auth/users",
        {"email": "who@example.com", "role": User.Role.STUDENT, "password": "short"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_create_user_forbidden_for_student(client):
    inst = _make_institution()
    _register(client, inst, email="student@example.com", role=User.Role.STUDENT)
    token = _token(client, inst, "student@example.com")

    resp = client.post(
        "/api/v1/auth/users",
        {"email": "new@example.com", "role": User.Role.STUDENT, "password": "n3w-passw0rd"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 403
    assert not User.objects.filter(email="new@example.com").exists()
