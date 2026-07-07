"""Task: platform superadmin cross-tenant endpoints.

Covers:
- POST /auth/institutions  -> superadmin creates an Institution (dup slug -> 400).
- GET  /auth/institutions  -> superadmin lists all institutions, newest first,
  excluding the operator-internal `platform` tenant.
- POST /auth/admins        -> superadmin provisions a role=admin User in a target
  institution, emitting exactly one user.registered outbox event.
- A non-superadmin (role admin) is forbidden (403) on all three.
"""

import pytest
from accounts.models import Institution, User
from rest_framework.test import APIClient
from suerp_common.outbox import OutboxEvent

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return APIClient()


def _make_institution(slug, name, is_active=True):
    return Institution.objects.create(slug=slug, name=name, is_active=is_active)


_user_code_counter = 0


def _next_user_code():
    global _user_code_counter
    _user_code_counter += 1
    return f"USR-{_user_code_counter:04d}"


def _make_user(institution, email, role, password="s3cur3-passw0rd", user_code=None, **extra):
    if role == User.Role.SUPERADMIN:
        return User.objects.create_superuser(
            tenant=institution, email=email, password=password, role=role, **extra
        )
    return User.objects.create_user(
        tenant=institution,
        email=email,
        password=password,
        role=role,
        user_code=user_code or _next_user_code(),
        **extra,
    )


def _token(client, institution, email, password="s3cur3-passw0rd"):
    resp = client.post(
        "/api/v1/auth/login",
        {"institution_slug": institution.slug, "email": email, "password": password},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    return resp.json()["data"]["access"]


def _superadmin_token(client):
    platform = _make_institution("platform", "Platform")
    _make_user(
        platform,
        "super@suerp.io",
        User.Role.SUPERADMIN,
        is_staff=True,
        is_superuser=True,
    )
    return _token(client, platform, "super@suerp.io")


def _admin_token(client):
    inst = _make_institution("alpha", "Alpha University")
    _make_user(inst, "admin@alpha.example.com", User.Role.ADMIN)
    return _token(client, inst, "admin@alpha.example.com")


# --- POST /auth/institutions ----------------------------------------------


def test_superadmin_creates_institution(client):
    token = _superadmin_token(client)

    resp = client.post(
        "/api/v1/auth/institutions",
        {"slug": "beta-univ", "name": "Beta University"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["slug"] == "beta-univ"
    assert data["name"] == "Beta University"
    assert data["is_active"] is True

    inst = Institution.objects.get(slug="beta-univ")
    assert data["id"] == str(inst.id)


def test_superadmin_create_institution_rejects_duplicate_slug(client):
    token = _superadmin_token(client)
    _make_institution("beta-univ", "Beta University")

    resp = client.post(
        "/api/v1/auth/institutions",
        {"slug": "beta-univ", "name": "Duplicate"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert Institution.objects.filter(slug="beta-univ").count() == 1


def test_create_institution_forbidden_for_admin(client):
    token = _admin_token(client)

    resp = client.post(
        "/api/v1/auth/institutions",
        {"slug": "sneaky", "name": "Sneaky"},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 403
    assert not Institution.objects.filter(slug="sneaky").exists()


# --- GET /auth/institutions -----------------------------------------------


def test_superadmin_lists_institutions_excluding_platform(client):
    token = _superadmin_token(client)
    _make_institution("alpha", "Alpha University")
    _make_institution("beta", "Beta University")

    resp = client.get("/api/v1/auth/institutions", HTTP_AUTHORIZATION=f"Bearer {token}")

    assert resp.status_code == 200, resp.content
    results = resp.json()["data"]["results"]
    slugs = [r["slug"] for r in results]
    assert "platform" not in slugs
    assert set(slugs) == {"alpha", "beta"}
    for r in results:
        assert set(r.keys()) == {"id", "slug", "name", "is_active", "created_at"}


def test_list_institutions_forbidden_for_admin(client):
    token = _admin_token(client)

    resp = client.get("/api/v1/auth/institutions", HTTP_AUTHORIZATION=f"Bearer {token}")

    assert resp.status_code == 403


# --- POST /auth/admins ----------------------------------------------------


def test_superadmin_creates_admin_in_target_institution_and_emits_one_event(client):
    token = _superadmin_token(client)
    target = _make_institution("gamma", "Gamma University")

    resp = client.post(
        "/api/v1/auth/admins",
        {
            "institution_slug": "gamma",
            "email": "admin@gamma.example.com",
            "password": "n3w-passw0rd",
            "user_code": "ADM-GAMMA",
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert data["email"] == "admin@gamma.example.com"
    assert data["role"] == User.Role.ADMIN
    assert data["institution_slug"] == "gamma"

    user = User.objects.get(tenant=target, email="admin@gamma.example.com")
    assert data["user_code"] == user.user_code
    assert user.role == User.Role.ADMIN
    assert user.check_password("n3w-passw0rd") is True

    events = OutboxEvent.objects.filter(
        type="user.registered", payload__user_code=user.user_code
    )
    assert events.count() == 1
    assert str(events.first().tenant_id) == str(target.id)
    assert events.first().payload["role"] == User.Role.ADMIN


def test_create_admin_unknown_institution_slug_rejected(client):
    token = _superadmin_token(client)

    resp = client.post(
        "/api/v1/auth/admins",
        {
            "institution_slug": "does-not-exist",
            "email": "admin@nowhere.example.com",
            "password": "n3w-passw0rd",
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert not User.objects.filter(email="admin@nowhere.example.com").exists()


def test_create_admin_inactive_institution_rejected(client):
    token = _superadmin_token(client)
    _make_institution("dormant", "Dormant University", is_active=False)

    resp = client.post(
        "/api/v1/auth/admins",
        {
            "institution_slug": "dormant",
            "email": "admin@dormant.example.com",
            "password": "n3w-passw0rd",
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 400
    assert not User.objects.filter(email="admin@dormant.example.com").exists()


def test_create_admin_rejects_duplicate_email(client):
    token = _superadmin_token(client)
    target = _make_institution("delta", "Delta University")
    _make_user(target, "dupe@delta.example.com", User.Role.ADMIN)

    resp = client.post(
        "/api/v1/auth/admins",
        {
            "institution_slug": "delta",
            "email": "dupe@delta.example.com",
            "password": "n3w-passw0rd",
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert User.objects.filter(tenant=target, email="dupe@delta.example.com").count() == 1


def test_create_admin_rejects_short_password(client):
    token = _superadmin_token(client)
    _make_institution("epsilon", "Epsilon University")

    resp = client.post(
        "/api/v1/auth/admins",
        {
            "institution_slug": "epsilon",
            "email": "admin@epsilon.example.com",
            "password": "short",
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 400
    assert not User.objects.filter(email="admin@epsilon.example.com").exists()


def test_create_admin_forbidden_for_admin(client):
    token = _admin_token(client)
    _make_institution("zeta", "Zeta University")

    resp = client.post(
        "/api/v1/auth/admins",
        {
            "institution_slug": "zeta",
            "email": "admin@zeta.example.com",
            "password": "n3w-passw0rd",
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 403
    assert not User.objects.filter(email="admin@zeta.example.com").exists()
