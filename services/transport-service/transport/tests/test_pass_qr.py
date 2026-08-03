"""QR bus passes: rolling mint, offline-verifiable, replay-resistant.

Tokens and fixtures follow this service's existing convention (see
test_schedules.py): pyjwt-minted tokens and ``all_objects`` for setup rows,
since no tenant is active outside a request.
"""

import uuid

import pytest
from rest_framework.test import APIClient
from suerp_common.signed_token import sign
from transport.models import Pass, Route, ScanLog
from transport.tests.test_schedules import _token

pytestmark = pytest.mark.django_db

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _client(tenant_id, role="student", sub="STU-001"):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token(tenant_id, user_id=sub, role=role)}")
    return client


def _pass(tenant_id, student="STU-001", active=True):
    route = Route.all_objects.create(
        tenant_id=tenant_id, name="North", start_point="Gate", end_point="Campus"
    )
    return Pass.all_objects.create(
        tenant_id=tenant_id, student_user_code=student, route=route, active=active
    )


def test_student_mints_a_qr_for_their_active_pass():
    _pass(TENANT_A)
    client = _client(TENANT_A)

    response = client.get("/api/v1/transport/passes/mine/qr")

    assert response.status_code == 200
    assert response.json()["data"]["token"]
    assert response.json()["data"]["expires_in"] == 30


def test_a_student_without_an_active_pass_gets_404():
    _pass(TENANT_A, active=False)
    client = _client(TENANT_A)

    response = client.get("/api/v1/transport/passes/mine/qr")

    assert response.status_code == 404


def test_driver_scan_accepts_a_fresh_token():
    bus_pass = _pass(TENANT_A)
    token = _client(TENANT_A).get("/api/v1/transport/passes/mine/qr").json()["data"]["token"]

    driver = _client(TENANT_A, role="driver", sub="DRV-001")
    response = driver.post("/api/v1/transport/scans", {"token": token}, format="json")

    assert response.status_code == 201
    assert response.json()["data"]["accepted"] is True
    assert response.json()["data"]["student_user_code"] == "STU-001"
    assert ScanLog.all_objects.filter(pass_id=bus_pass.id, accepted=True).count() == 1


def test_the_same_token_cannot_be_scanned_twice():
    """A screenshotted QR replayed at the next stop must not board again."""
    _pass(TENANT_A)
    token = _client(TENANT_A).get("/api/v1/transport/passes/mine/qr").json()["data"]["token"]
    driver = _client(TENANT_A, role="driver", sub="DRV-001")
    driver.post("/api/v1/transport/scans", {"token": token}, format="json")

    response = driver.post("/api/v1/transport/scans", {"token": token}, format="json")

    assert response.status_code == 409
    assert ScanLog.all_objects.filter(accepted=False).count() == 1


def test_a_tampered_token_is_rejected():
    _pass(TENANT_A)
    token = _client(TENANT_A).get("/api/v1/transport/passes/mine/qr").json()["data"]["token"]
    driver = _client(TENANT_A, role="driver", sub="DRV-001")

    response = driver.post(
        "/api/v1/transport/scans", {"token": token[:-4] + "AAAA"}, format="json"
    )

    assert response.status_code == 400


def test_a_pass_token_from_another_tenant_is_rejected():
    token = sign(
        {"kind": "bus_pass", "tenant_id": str(TENANT_B), "pass_id": str(uuid.uuid4())},
        ttl_seconds=30,
    )
    driver = _client(TENANT_A, role="driver", sub="DRV-001")

    response = driver.post("/api/v1/transport/scans", {"token": token}, format="json")

    assert response.status_code == 400


def test_students_cannot_scan():
    _pass(TENANT_A)
    token = _client(TENANT_A).get("/api/v1/transport/passes/mine/qr").json()["data"]["token"]
    other_student = _client(TENANT_A, sub="STU-002")

    response = other_student.post("/api/v1/transport/scans", {"token": token}, format="json")

    assert response.status_code == 403


def test_only_scanners_can_fetch_the_verification_key():
    assert _client(TENANT_A).get("/api/v1/transport/scan-key").status_code == 403
    assert (
        _client(TENANT_A, role="driver", sub="DRV-001")
        .get("/api/v1/transport/scan-key")
        .status_code
        == 200
    )
