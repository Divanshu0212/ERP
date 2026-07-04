"""GET /auth/users/by-email/ — resolve an email to its User.id within the
caller's own tenant. Every student_id/warden_id in this platform IS the
auth-service User.id (see the design spec), so this single endpoint is
the whole identity-resolution story for hostel-service's email-based
allocation and block-creation flows.
"""

import pytest
from accounts.models import Institution, User
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

ENDPOINT = "/api/v1/auth/users/by-email/"


def _make_institution(slug="alpha", name="Alpha University"):
    return Institution.objects.create(slug=slug, name=name, is_active=True)


@pytest.fixture
def client():
    return APIClient()


def _register(client, institution, email, password="s3cur3-passw0rd", role=None):
    payload = {"institution_slug": institution.slug, "email": email, "password": password}
    if role is not None:
        payload["role"] = role
    resp = client.post("/api/v1/auth/register", payload, format="json")
    assert resp.status_code == 201, resp.content
    return resp.json()["data"]


def _token(client, institution, email, password="s3cur3-passw0rd"):
    resp = client.post(
        "/api/v1/auth/login",
        {"institution_slug": institution.slug, "email": email, "password": password},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    return resp.json()["data"]["access"]


def _warden_token(client, institution, email="warden@example.com"):
    _register(client, institution, email=email, role=User.Role.WARDEN)
    return _token(client, institution, email)


def test_warden_finds_student_by_email(client):
    inst = _make_institution()
    warden_token = _warden_token(client, inst)
    student = _register(client, inst, email="student@example.com", role=User.Role.STUDENT)

    resp = client.get(
        f"{ENDPOINT}?email=student@example.com",
        HTTP_AUTHORIZATION=f"Bearer {warden_token}",
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == {"id": student["id"], "email": "student@example.com", "role": "student"}


def test_returns_404_for_unknown_email(client):
    inst = _make_institution()
    warden_token = _warden_token(client, inst)

    resp = client.get(
        f"{ENDPOINT}?email=nobody@example.com",
        HTTP_AUTHORIZATION=f"Bearer {warden_token}",
    )

    assert resp.status_code == 404
    assert resp.json()["success"] is False


def test_lookup_is_tenant_scoped(client):
    inst_a = _make_institution(slug="alpha", name="Alpha University")
    inst_b = _make_institution(slug="beta", name="Beta University")
    warden_token = _warden_token(client, inst_a)
    _register(client, inst_b, email="student@example.com", role=User.Role.STUDENT)

    resp = client.get(
        f"{ENDPOINT}?email=student@example.com",
        HTTP_AUTHORIZATION=f"Bearer {warden_token}",
    )

    assert resp.status_code == 404


def test_student_role_cannot_use_lookup(client):
    inst = _make_institution()
    _register(client, inst, email="student@example.com", role=User.Role.STUDENT)
    student_token = _token(client, inst, "student@example.com")

    resp = client.get(
        f"{ENDPOINT}?email=student@example.com",
        HTTP_AUTHORIZATION=f"Bearer {student_token}",
    )

    assert resp.status_code == 403


def test_missing_email_param_is_400(client):
    inst = _make_institution()
    warden_token = _warden_token(client, inst)

    resp = client.get(ENDPOINT, HTTP_AUTHORIZATION=f"Bearer {warden_token}")

    assert resp.status_code == 400


def test_requires_authentication(client):
    resp = client.get(f"{ENDPOINT}?email=student@example.com")
    assert resp.status_code == 401
