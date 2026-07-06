"""Student room requests: create + list-own (hostel/models.py: RoomRequest).

Warden approve/reject endpoints are covered in test_room_request_approval.py
(Task 2) — this file only covers the student-facing half.
"""

import uuid

import pytest

pytestmark = pytest.mark.django_db

from hostel.models import RoomRequest
from hostel.tests.test_allocate import _auth_client, _make_room


def test_student_can_create_room_request():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    student_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="student", user_id=student_id)

    response = client.post(
        "/api/v1/hostel/room-requests",
        {"room_id": str(room.id)},
        format="json",
    )

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["status"] == "pending"
    assert body["room_id"] == str(room.id)

    req = RoomRequest.all_objects.get(id=body["id"])
    assert req.student_id == student_id
    assert req.tenant_id == tenant_id


def test_student_cannot_request_full_room():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=1, occupied_count=1, room_no="101")
    client = _auth_client(tenant_id, role="student")

    response = client.post(
        "/api/v1/hostel/room-requests",
        {"room_id": str(room.id)},
        format="json",
    )

    assert response.status_code == 400


def test_student_lists_only_own_requests():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=3, occupied_count=0, room_no="101")
    student_a = uuid.uuid4()
    student_b = uuid.uuid4()

    client_a = _auth_client(tenant_id, role="student", user_id=student_a)
    client_a.post("/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json")

    client_b = _auth_client(tenant_id, role="student", user_id=student_b)
    client_b.post("/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json")

    response = client_a.get("/api/v1/hostel/room-requests/mine")
    assert response.status_code == 200
    items = response.json()["data"]["results"] if "results" in response.json()["data"] else response.json()["data"]
    student_ids = {item.get("student_id") for item in items} if items and "student_id" in items[0] else None
    assert len(items) == 1


def test_warden_role_forbidden_from_student_create():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/room-requests",
        {"room_id": str(room.id)},
        format="json",
    )

    assert response.status_code == 403
