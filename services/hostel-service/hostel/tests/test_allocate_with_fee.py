"""AllocateView / ApproveRoomRequestView: fee_structure_id and due_date are
optional but must be given together (both or neither). Neither given ->
direct allocation, confirmed immediately.
"""

import uuid
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db

from hostel.models import Allocation, RoomRequest  # noqa: E402
from hostel.tests.test_allocate import _auth_client, _make_room  # noqa: E402


@patch("hostel.views.resolve_user_by_code")
def test_allocate_with_no_fee_confirms_immediately(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    mock_resolve.return_value = {"user_code": "STU001"}
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {"room_id": str(room.id), "student_user_code": "STU001"},
        format="json",
    )

    assert response.status_code == 201, response.content
    assert response.json()["data"]["status"] == "confirmed"


@patch("hostel.views.resolve_user_by_code")
def test_allocate_with_fee_requires_due_date(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    mock_resolve.return_value = {"user_code": "STU001"}
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {
            "room_id": str(room.id),
            "student_user_code": "STU001",
            "fee_structure_id": str(uuid.uuid4()),
        },
        format="json",
    )

    assert response.status_code == 400
    assert Allocation.all_objects.filter(tenant_id=tenant_id).count() == 0


@patch("hostel.views.resolve_user_by_code")
def test_allocate_with_fee_and_due_date_stays_pending(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    mock_resolve.return_value = {"user_code": "STU001"}
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {
            "room_id": str(room.id),
            "student_user_code": "STU001",
            "fee_structure_id": str(uuid.uuid4()),
            "due_date": "2026-08-01",
        },
        format="json",
    )

    assert response.status_code == 201, response.content
    assert response.json()["data"]["status"] == "pending"


@patch("hostel.views.requests.get")
def test_approve_with_no_fee_confirms_immediately(mock_get):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    student_id = f"STU-{uuid.uuid4().hex[:8]}"
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
    response = warden_client.post(
        f"/api/v1/hostel/room-requests/{request_id}/approve", {}, format="json"
    )

    assert response.status_code == 200, response.content
    assert response.json()["data"]["status"] == "approved"
    allocation = Allocation.all_objects.get(student_user_code=student_id, tenant_id=tenant_id)
    assert allocation.status == "confirmed"


@patch("hostel.views.resolve_user_by_code")
def test_allocate_rejects_past_due_date(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    mock_resolve.return_value = {"user_code": "STU001"}
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {
            "room_id": str(room.id),
            "student_user_code": "STU001",
            "fee_structure_id": str(uuid.uuid4()),
            "due_date": "2020-01-01",
        },
        format="json",
    )

    assert response.status_code == 400
    assert Allocation.all_objects.filter(tenant_id=tenant_id).count() == 0


@patch("hostel.views.requests.get")
def test_approve_rejects_past_due_date(mock_get):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    student_id = f"STU-{uuid.uuid4().hex[:8]}"
    student_client = _auth_client(tenant_id, role="student", user_id=student_id)
    create_response = student_client.post(
        "/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json"
    )
    request_id = create_response.json()["data"]["id"]

    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.post(
        f"/api/v1/hostel/room-requests/{request_id}/approve",
        {"fee_structure_id": str(uuid.uuid4()), "due_date": "2020-01-01"},
        format="json",
    )

    assert response.status_code == 400
    request = RoomRequest.all_objects.get(id=request_id)
    assert request.status == "pending"  # not flipped to approved


@patch("hostel.views.requests.get")
def test_approve_with_fee_requires_due_date(mock_get):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    student_id = f"STU-{uuid.uuid4().hex[:8]}"
    student_client = _auth_client(tenant_id, role="student", user_id=student_id)
    create_response = student_client.post(
        "/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json"
    )
    request_id = create_response.json()["data"]["id"]

    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.post(
        f"/api/v1/hostel/room-requests/{request_id}/approve",
        {"fee_structure_id": str(uuid.uuid4())},
        format="json",
    )

    assert response.status_code == 400
    request = RoomRequest.all_objects.get(id=request_id)
    assert request.status == "pending"  # not flipped to approved
