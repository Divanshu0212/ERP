"""Warden approve/reject on a student RoomRequest (hostel/models.py:
RoomRequest). Approval calls the existing create_allocation() unchanged (same
lock/capacity-check/atomic-commit/outbox path AllocateView already uses),
extended with fee_structure_id/university_name flowing into the
hostel.allocation.requested event payload for finance-service to consume.
"""

import uuid
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db

from hostel.models import Allocation, RoomRequest  # noqa: E402
from hostel.tests.test_allocate import _auth_client, _make_room  # noqa: E402
from suerp_common.outbox import OutboxEvent  # noqa: E402


@patch("hostel.views.requests.get")
def test_warden_approves_request_creates_allocation_with_fee_and_university(mock_get):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    student_id = uuid.uuid4()

    student_client = _auth_client(tenant_id, role="student", user_id=student_id)
    create_response = student_client.post(
        "/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json"
    )
    request_id = create_response.json()["data"]["id"]

    mock_get.return_value.status_code = 200
    mock_get.return_value.ok = True
    mock_get.return_value.json.return_value = {
        "success": True,
        "data": {"id": str(tenant_id), "slug": "test-uni", "name": "Test University"},
    }

    fee_structure_id = uuid.uuid4()
    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.post(
        f"/api/v1/hostel/room-requests/{request_id}/approve",
        {"fee_structure_id": str(fee_structure_id)},
        format="json",
    )

    assert response.status_code == 200, response.content
    body = response.json()["data"]
    assert body["status"] == "approved"

    req = RoomRequest.all_objects.get(id=request_id)
    assert req.status == "approved"
    assert req.decided_on is not None

    allocation = Allocation.all_objects.get(student_id=student_id, tenant_id=tenant_id)
    assert allocation.status == "pending"

    event = OutboxEvent.objects.get(tenant_id=tenant_id, type="hostel.allocation.requested")
    assert event.payload["fee_structure_id"] == str(fee_structure_id)
    assert event.payload["university_name"] == "Test University"


@patch("hostel.views.requests.get")
def test_double_approve_does_not_create_second_allocation(mock_get):
    """A replayed/duplicate approve on an already-approved request returns a
    clean 400 "already decided" and does NOT create a second Allocation."""
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    student_id = uuid.uuid4()

    student_client = _auth_client(tenant_id, role="student", user_id=student_id)
    create_response = student_client.post(
        "/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json"
    )
    request_id = create_response.json()["data"]["id"]

    mock_get.return_value.status_code = 200
    mock_get.return_value.ok = True
    mock_get.return_value.json.return_value = {
        "success": True,
        "data": {"id": str(tenant_id), "slug": "test-uni", "name": "Test University"},
    }

    warden_client = _auth_client(tenant_id, role="warden")
    fee_structure_id = uuid.uuid4()

    first = warden_client.post(
        f"/api/v1/hostel/room-requests/{request_id}/approve",
        {"fee_structure_id": str(fee_structure_id)},
        format="json",
    )
    assert first.status_code == 200, first.content

    second = warden_client.post(
        f"/api/v1/hostel/room-requests/{request_id}/approve",
        {"fee_structure_id": str(fee_structure_id)},
        format="json",
    )
    assert second.status_code == 400, second.content

    assert (
        Allocation.all_objects.filter(student_id=student_id, tenant_id=tenant_id).count() == 1
    )


def test_warden_rejects_request():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    student_client = _auth_client(tenant_id, role="student")
    create_response = student_client.post(
        "/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json"
    )
    request_id = create_response.json()["data"]["id"]

    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.post(
        f"/api/v1/hostel/room-requests/{request_id}/reject",
        {"rejection_reason": "Room reserved for staff."},
        format="json",
    )

    assert response.status_code == 200, response.content
    req = RoomRequest.all_objects.get(id=request_id)
    assert req.status == "rejected"
    assert req.rejection_reason == "Room reserved for staff."
    assert Allocation.all_objects.filter(tenant_id=tenant_id).count() == 0


def test_student_role_forbidden_from_approve():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    student_client = _auth_client(tenant_id, role="student")
    create_response = student_client.post(
        "/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json"
    )
    request_id = create_response.json()["data"]["id"]

    response = student_client.post(
        f"/api/v1/hostel/room-requests/{request_id}/approve",
        {"fee_structure_id": str(uuid.uuid4())},
        format="json",
    )
    assert response.status_code == 403


def test_pending_list_shows_only_pending():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    student_client = _auth_client(tenant_id, role="student")
    student_client.post("/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json")

    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.get("/api/v1/hostel/room-requests?status=pending")

    assert response.status_code == 200
    items = response.json()["data"]
    results = items["results"] if isinstance(items, dict) and "results" in items else items
    assert len(results) == 1
    assert results[0]["status"] == "pending"
