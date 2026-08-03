"""Warden visitor log: gate entries recorded on a phone, often offline.

Tokens come from ``test_allocate._auth_client`` — this service's existing
helper — rather than a new one, so these tests authenticate exactly the way
every other hostel test does.
"""

import uuid

import pytest

pytestmark = pytest.mark.django_db

from hostel.tests.test_allocate import _auth_client  # noqa: E402

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _client(tenant_id, role="warden", sub="WRD-001"):
    return _auth_client(tenant_id, role=role, user_id=sub)


def test_warden_can_log_a_visitor():
    client = _client(TENANT_A)

    response = client.post(
        "/api/v1/hostel/visitors",
        {"visitor_name": "Asha Rao", "visiting_user_code": "STU-001", "purpose": "Parent visit"},
        format="json",
    )

    assert response.status_code == 201, response.content
    assert response.json()["data"]["visitor_name"] == "Asha Rao"
    assert response.json()["data"]["checked_out_at"] is None


def test_checkout_stamps_the_exit_time():
    client = _client(TENANT_A)
    created = client.post(
        "/api/v1/hostel/visitors",
        {"visitor_name": "Asha Rao", "visiting_user_code": "STU-001", "purpose": "Parent visit"},
        format="json",
    ).json()["data"]

    response = client.post(f"/api/v1/hostel/visitors/{created['id']}/checkout", format="json")

    assert response.status_code == 200, response.content
    assert response.json()["data"]["checked_out_at"] is not None


def test_checking_out_twice_is_rejected():
    client = _client(TENANT_A)
    created = client.post(
        "/api/v1/hostel/visitors",
        {"visitor_name": "Asha Rao", "visiting_user_code": "STU-001", "purpose": "Visit"},
        format="json",
    ).json()["data"]
    client.post(f"/api/v1/hostel/visitors/{created['id']}/checkout", format="json")

    response = client.post(f"/api/v1/hostel/visitors/{created['id']}/checkout", format="json")

    assert response.status_code == 400


def test_students_cannot_log_visitors():
    client = _client(TENANT_A, role="student", sub="STU-001")

    response = client.post(
        "/api/v1/hostel/visitors",
        {"visitor_name": "Asha Rao", "visiting_user_code": "STU-001", "purpose": "Visit"},
        format="json",
    )

    assert response.status_code == 403


def test_visitor_logs_do_not_leak_across_tenants():
    client_a = _client(TENANT_A)
    client_a.post(
        "/api/v1/hostel/visitors",
        {"visitor_name": "Asha Rao", "visiting_user_code": "STU-001", "purpose": "Visit"},
        format="json",
    )

    client_b = _client(TENANT_B, sub="WRD-002")
    response = client_b.get("/api/v1/hostel/visitors")

    assert response.status_code == 200, response.content
    assert response.json()["data"]["results"] == []
