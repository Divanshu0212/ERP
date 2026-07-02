"""End-to-end tests for Task 3.3: register / login / refresh / me.

Covers tenant-scoped authentication, JWT claim shape (sub/role/tenant, the
exact keys ``suerp_common.auth.JWTAuthentication`` reads), and the
LoginAudit-backed lockout policy.
"""

import jwt
import pytest
from accounts.models import Institution, LoginAudit, User
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def _make_institution(slug="alpha", name="Alpha University", is_active=True):
    return Institution.objects.create(slug=slug, name=name, is_active=is_active)


@pytest.fixture
def client():
    return APIClient()


def _register(
    client, institution, email="student@example.com", password="s3cur3-passw0rd", role=None
):
    payload = {
        "institution_slug": institution.slug,
        "email": email,
        "password": password,
    }
    if role is not None:
        payload["role"] = role
    return client.post("/api/v1/auth/register", payload, format="json")


def _login(client, institution, email="student@example.com", password="s3cur3-passw0rd"):
    return client.post(
        "/api/v1/auth/login",
        {"institution_slug": institution.slug, "email": email, "password": password},
        format="json",
    )


def test_register_creates_user_with_hashed_password(client):
    inst = _make_institution()

    response = _register(client, inst)

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["email"] == "student@example.com"
    assert body["data"]["role"] == User.Role.STUDENT

    user = User.objects.get(tenant=inst, email="student@example.com")
    assert user.password != "s3cur3-passw0rd"
    assert user.check_password("s3cur3-passw0rd") is True


def test_register_rejects_unknown_institution_slug(client):
    response = client.post(
        "/api/v1/auth/register",
        {
            "institution_slug": "does-not-exist",
            "email": "a@example.com",
            "password": "s3cur3-passw0rd",
        },
        format="json",
    )

    assert response.status_code in (400, 404)
    body = response.json()
    assert body["success"] is False


def test_register_rejects_inactive_institution(client):
    inst = _make_institution(slug="inactive-school", is_active=False)

    response = _register(client, inst)

    assert response.status_code in (400, 404)
    assert response.json()["success"] is False


def test_login_returns_tokens_with_correct_claims(client):
    inst = _make_institution()
    _register(client, inst)
    user = User.objects.get(tenant=inst, email="student@example.com")

    response = _login(client, inst)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    access = body["data"]["access"]
    refresh = body["data"]["refresh"]
    assert access and refresh

    claims = jwt.decode(access, settings.JWT_SIGNING_KEY, algorithms=["HS256"])
    assert claims["sub"] == str(user.id)
    assert claims["role"] == user.role
    assert claims["tenant"] == str(inst.id)


def test_login_writes_success_audit(client):
    inst = _make_institution()
    _register(client, inst)

    _login(client, inst)

    assert LoginAudit.objects.filter(
        tenant=inst, email="student@example.com", success=True
    ).exists()


def test_me_endpoint_returns_current_user(client):
    inst = _make_institution()
    _register(client, inst)
    login_response = _login(client, inst)
    access = login_response.json()["data"]["access"]

    response = client.get("/api/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {access}")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["email"] == "student@example.com"
    assert body["data"]["role"] == User.Role.STUDENT
    assert body["data"]["tenant"] == str(inst.id)


def test_me_endpoint_requires_token(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_wrong_password_writes_failure_audit_and_401s(client):
    inst = _make_institution()
    _register(client, inst)

    response = _login(client, inst, password="wrong-password")

    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False
    assert LoginAudit.objects.filter(
        tenant=inst, email="student@example.com", success=False
    ).exists()


def test_five_failed_logins_lock_out_the_sixth_even_with_correct_password(client):
    inst = _make_institution()
    _register(client, inst)

    for _ in range(5):
        resp = _login(client, inst, password="wrong-password")
        assert resp.status_code == 401

    response = _login(client, inst)  # correct password on the 6th attempt

    assert response.status_code == 429
    body = response.json()
    assert body["success"] is False


def test_lockout_is_scoped_to_institution_and_email_window(client):
    inst = _make_institution()
    _register(client, inst)

    # Only 4 failures -> not locked yet, correct password still works.
    for _ in range(4):
        _login(client, inst, password="wrong-password")

    response = _login(client, inst)

    assert response.status_code == 200


def test_lockout_ignores_failures_outside_the_window(client):
    inst = _make_institution()
    _register(client, inst)

    for _ in range(5):
        _login(client, inst, password="wrong-password")
    # Push all failure timestamps outside the lockout window.
    LoginAudit.objects.filter(tenant=inst, email="student@example.com").update(
        timestamp=timezone.now() - timezone.timedelta(minutes=30)
    )

    response = _login(client, inst)

    assert response.status_code == 200


def test_same_email_different_institutions_are_authenticated_independently(client):
    inst_a = _make_institution(slug="alpha", name="Alpha University")
    inst_b = _make_institution(slug="beta", name="Beta University")

    _register(client, inst_a, password="passw0rd-alpha")
    _register(client, inst_b, password="passw0rd-beta")

    # Wrong-institution password fails.
    resp_wrong = _login(client, inst_b, password="passw0rd-alpha")
    assert resp_wrong.status_code == 401

    # Correct per-institution password succeeds and returns that tenant's claim.
    resp_b = _login(client, inst_b, password="passw0rd-beta")
    assert resp_b.status_code == 200
    claims_b = jwt.decode(
        resp_b.json()["data"]["access"], settings.JWT_SIGNING_KEY, algorithms=["HS256"]
    )
    assert claims_b["tenant"] == str(inst_b.id)

    user_b = User.objects.get(tenant=inst_b, email="student@example.com")
    assert claims_b["sub"] == str(user_b.id)


def test_refresh_endpoint_issues_new_access_token(client):
    inst = _make_institution()
    _register(client, inst)
    login_response = _login(client, inst)
    refresh = login_response.json()["data"]["refresh"]

    response = client.post("/api/v1/auth/refresh", {"refresh": refresh}, format="json")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert "access" in body["data"]
