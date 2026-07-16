"""POST /api/v1/auth/users/bulk/ — admin bulk student creation.

Covers: all-success, mixed success/fail (dup email/user_code against
existing DB rows AND against earlier rows in the same batch), permission
(admin-only), malformed body, and the user.registered event payload
carrying department/batch/semester for the consumer in student-service.
"""

import pytest
from accounts.models import Institution, User
from rest_framework.test import APIClient
from suerp_common.outbox import OutboxEvent

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


def _row(
    email="stu1@example.com",
    user_code="STU-0001",
    password="n3w-passw0rd",
    department="CS",
    batch="2026",
    semester=1,
):
    return {
        "email": email,
        "user_code": user_code,
        "password": password,
        "department": department,
        "batch": batch,
        "semester": semester,
    }


def test_bulk_create_all_success(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {
            "rows": [
                _row(email="a@example.com", user_code="STU-A"),
                _row(email="b@example.com", user_code="STU-B"),
            ]
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert len(data["created"]) == 2
    assert data["failed"] == []
    assert {c["email"] for c in data["created"]} == {"a@example.com", "b@example.com"}

    a = User.objects.get(tenant=inst, email="a@example.com")
    assert a.role == User.Role.STUDENT
    assert a.check_password("n3w-passw0rd") is True

    events = OutboxEvent.objects.filter(type="user.registered", payload__user_code="STU-A")
    assert events.count() == 1
    payload = events.first().payload
    assert payload["role"] == User.Role.STUDENT
    assert payload["department"] == "CS"
    assert payload["batch"] == "2026"
    assert payload["semester"] == 1


def test_bulk_create_mixed_success_and_failure_does_not_abort_batch(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)
    _register(
        client, inst, email="existing@example.com", role=User.Role.STUDENT, user_code="EXIST-1"
    )

    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {
            "rows": [
                _row(email="good@example.com", user_code="STU-GOOD"),
                _row(email="existing@example.com", user_code="STU-DUPE-EMAIL"),  # dup email vs DB
                _row(email="dupcode@example.com", user_code="EXIST-1"),  # dup user_code vs DB
            ]
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert len(data["created"]) == 1
    assert data["created"][0]["email"] == "good@example.com"
    assert len(data["failed"]) == 2
    failed_rows = {f["row"] for f in data["failed"]}
    assert failed_rows == {1, 2}  # 0-indexed: row 0 succeeded
    assert User.objects.filter(tenant=inst, email="good@example.com").exists()
    assert not User.objects.filter(tenant=inst, email="dupcode@example.com").exists()


def test_bulk_create_rejects_duplicate_within_same_batch(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {
            "rows": [
                _row(email="same@example.com", user_code="STU-SAME-1"),
                _row(email="same@example.com", user_code="STU-SAME-2"),
            ]
        },
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert len(data["created"]) == 1
    assert len(data["failed"]) == 1
    assert data["failed"][0]["row"] == 1


def test_bulk_create_empty_rows_is_400(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {"rows": []},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_bulk_create_missing_rows_key_is_400(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 400


def test_bulk_create_forbidden_for_student(client):
    inst = _make_institution()
    _register(client, inst, email="student@example.com", role=User.Role.STUDENT)
    token = _token(client, inst, "student@example.com")

    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {"rows": [_row()]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 403


def test_bulk_create_requires_authentication(client):
    resp = client.post("/api/v1/auth/users/bulk/", {"rows": [_row()]}, format="json")
    assert resp.status_code == 401


def test_bulk_create_isolated_per_tenant(client):
    inst_a = _make_institution(slug="alpha", name="Alpha University")
    inst_b = _make_institution(slug="beta", name="Beta University")
    admin_token_a = _admin_token(client, inst_a)
    _register(client, inst_b, email="stu@example.com", role=User.Role.STUDENT, user_code="STU-B1")

    # Same email exists in tenant B but not tenant A — must succeed for A.
    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {"rows": [_row(email="stu@example.com", user_code="STU-A1")]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )

    assert resp.status_code == 201, resp.content
    assert len(resp.json()["data"]["created"]) == 1
    assert User.objects.filter(tenant=inst_a, email="stu@example.com").exists()
