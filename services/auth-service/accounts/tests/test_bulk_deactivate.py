"""POST /api/v1/auth/users/bulk-delete/ — admin bulk user soft-delete.

Covers: all-success (is_active flips to False, row NOT removed), mixed
success/fail (unknown user_code, self-delete, last-admin), permission
(admin-only), malformed body, and tenant isolation.
"""

import pytest
from accounts.models import Institution, User
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def _make_institution(slug="alpha", name="Alpha University"):
    return Institution.objects.create(slug=slug, name=name, is_active=True)


@pytest.fixture
def client():
    return APIClient()


_user_code_counter = 0


def _next_user_code():
    global _user_code_counter
    _user_code_counter += 1
    return f"USR-{_user_code_counter:04d}"


def _register(client, institution, email, password="s3cur3-passw0rd", role=None, user_code=None):
    payload = {
        "institution_slug": institution.slug,
        "email": email,
        "password": password,
        "user_code": user_code or _next_user_code(),
    }
    if role is not None:
        payload["role"] = role
    resp = client.post("/api/v1/auth/register", payload, format="json")
    assert resp.status_code == 201, resp.content
    return resp.json()["data"]["user_code"]


def _token(client, institution, email, password="s3cur3-passw0rd"):
    resp = client.post(
        "/api/v1/auth/login",
        {"institution_slug": institution.slug, "email": email, "password": password},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    return resp.json()["data"]["access"]


def _admin(client, institution, email="admin@example.com"):
    code = _register(client, institution, email=email, role=User.Role.ADMIN)
    token = _token(client, institution, email)
    return code, token


def test_bulk_deactivate_all_success(client):
    inst = _make_institution()
    admin_code, admin_token = _admin(client, inst)
    stu_code = _register(client, inst, email="stu@example.com", role=User.Role.STUDENT)

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [stu_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert len(data["deactivated"]) == 1
    assert data["deactivated"][0]["user_code"] == stu_code
    assert data["failed"] == []

    stu = User.objects.get(pk=stu_code)
    assert stu.is_active is False


def test_bulk_deactivate_does_not_hard_delete(client):
    inst = _make_institution()
    _admin_code, admin_token = _admin(client, inst)
    stu_code = _register(client, inst, email="stu@example.com", role=User.Role.STUDENT)

    client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [stu_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert User.objects.filter(pk=stu_code).exists()


def test_bulk_deactivate_blocks_self_delete(client):
    inst = _make_institution()
    admin_code, admin_token = _admin(client, inst)
    _admin(client, inst, email="admin2@example.com")  # second admin so last-admin guard doesn't also fire

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [admin_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert data["deactivated"] == []
    assert len(data["failed"]) == 1
    assert data["failed"][0]["user_code"] == admin_code
    assert "own account" in data["failed"][0]["error"].lower()
    assert User.objects.get(pk=admin_code).is_active is True


def test_bulk_deactivate_blocks_last_admin(client):
    inst = _make_institution()
    admin_a, token_a = _admin(client, inst)
    admin_b, _token_b = _admin(client, inst, email="adminb@example.com")

    # A third admin, used purely as the CALLER below so the guard under
    # test is last-admin, not self-delete. Deactivated immediately so it
    # never counts as an "other active admin" itself.
    admin_c, token_c = _admin(client, inst, email="adminc@example.com")
    User.objects.filter(pk=admin_c).update(is_active=False)

    # Deactivate B, leaving A as the sole active admin.
    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [admin_b]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token_a}",
    )
    assert resp.status_code == 200, resp.content
    assert resp.json()["data"]["deactivated"] == [{"user_code": admin_b, "email": "adminb@example.com"}]

    # C (not the target, and itself already inactive) attempts to deactivate
    # A, the last remaining active admin — must be blocked, distinct from
    # self-delete since the caller (C) is not the target (A).
    resp2 = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [admin_a]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token_c}",
    )
    assert resp2.status_code == 200, resp2.content
    data2 = resp2.json()["data"]
    assert data2["deactivated"] == []
    assert data2["failed"][0]["user_code"] == admin_a
    assert "last active admin" in data2["failed"][0]["error"].lower()
    assert User.objects.get(pk=admin_a).is_active is True


def test_bulk_deactivate_last_admin_guard_uses_current_admin_count(client):
    """Regression test for the last-admin guard's row-locking fix: the
    active-admin count must reflect admins deactivated earlier in THIS
    same request, not a stale snapshot taken before the loop started."""
    inst = _make_institution()
    admin_a, admin_token = _admin(client, inst)
    admin_b, _ = _admin(client, inst, email="adminb@example.com")

    # Single request deactivates B first, then (in the same request) tries
    # to deactivate A — since B is now inactive, A IS the last admin and
    # must be blocked, even though at request-start there were 2 admins.
    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [admin_b, admin_a]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    # admin_b succeeds; admin_a is the caller's own account too, so it's
    # blocked by self-delete rather than last-admin — but either guard
    # firing proves the endpoint didn't leave zero active admins.
    assert {d["user_code"] for d in data["deactivated"]} == {admin_b}
    assert {f["user_code"] for f in data["failed"]} == {admin_a}
    assert User.objects.filter(tenant=inst, role=User.Role.ADMIN, is_active=True).count() == 1


def test_bulk_deactivate_unknown_user_code_fails_gracefully(client):
    inst = _make_institution()
    _admin_code, admin_token = _admin(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": ["NOPE-1"]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert data["deactivated"] == []
    assert data["failed"][0]["user_code"] == "NOPE-1"


def test_bulk_deactivate_mixed_success_and_failure(client):
    inst = _make_institution()
    admin_code, admin_token = _admin(client, inst)
    stu_code = _register(client, inst, email="stu@example.com", role=User.Role.STUDENT)

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [stu_code, "NOPE-1", admin_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert len(data["deactivated"]) == 1
    assert data["deactivated"][0]["user_code"] == stu_code
    assert len(data["failed"]) == 2
    failed_codes = {f["user_code"] for f in data["failed"]}
    assert failed_codes == {"NOPE-1", admin_code}


def test_bulk_deactivate_empty_list_is_400(client):
    inst = _make_institution()
    _admin_code, admin_token = _admin(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": []},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 400


def test_bulk_deactivate_missing_key_is_400(client):
    inst = _make_institution()
    _admin_code, admin_token = _admin(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 400


def test_bulk_deactivate_forbidden_for_student(client):
    inst = _make_institution()
    _register(client, inst, email="student@example.com", role=User.Role.STUDENT)
    token = _token(client, inst, "student@example.com")

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": ["whatever"]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 403


def test_bulk_deactivate_requires_authentication(client):
    resp = client.post("/api/v1/auth/users/bulk-delete/", {"user_codes": ["x"]}, format="json")
    assert resp.status_code == 401


def test_bulk_deactivate_isolated_per_tenant(client):
    inst_a = _make_institution(slug="alpha", name="Alpha University")
    inst_b = _make_institution(slug="beta", name="Beta University")
    _admin_a_code, admin_a_token = _admin(client, inst_a)
    stu_b_code = _register(client, inst_b, email="stu@example.com", role=User.Role.STUDENT)

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [stu_b_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_a_token}",
    )

    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert data["deactivated"] == []
    assert data["failed"][0]["user_code"] == stu_b_code
    assert User.objects.get(pk=stu_b_code).is_active is True
