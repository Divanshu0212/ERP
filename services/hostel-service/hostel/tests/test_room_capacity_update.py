"""PATCH /api/v1/hostel/rooms/<id> — admin edits room capacity.

Increasing is always allowed. Decreasing below the room's current
occupied_count is rejected with a 400 — a room can never show fewer seats
than students already living in it.
"""

import uuid

import pytest

pytestmark = pytest.mark.django_db

from hostel.tests.test_allocate import _auth_client, _make_room  # noqa: E402


def test_admin_increases_capacity():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1, room_no="101")
    client = _auth_client(tenant_id, role="admin")

    response = client.patch(f"/api/v1/hostel/rooms/{room.id}", {"capacity": 4}, format="json")

    assert response.status_code == 200, response.content
    body = response.json()["data"]
    assert body["capacity"] == 4

    room.refresh_from_db()
    assert room.capacity == 4


def test_admin_decreases_capacity_above_occupied_count():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=4, occupied_count=1, room_no="101")
    client = _auth_client(tenant_id, role="admin")

    response = client.patch(f"/api/v1/hostel/rooms/{room.id}", {"capacity": 2}, format="json")

    assert response.status_code == 200, response.content
    room.refresh_from_db()
    assert room.capacity == 2


def test_rejects_capacity_below_occupied_count():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=4, occupied_count=3, room_no="101")
    client = _auth_client(tenant_id, role="admin")

    response = client.patch(f"/api/v1/hostel/rooms/{room.id}", {"capacity": 2}, format="json")

    assert response.status_code == 400, response.content
    room.refresh_from_db()
    assert room.capacity == 4  # unchanged


def test_warden_forbidden_from_updating_capacity():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    client = _auth_client(tenant_id, role="warden")

    response = client.patch(f"/api/v1/hostel/rooms/{room.id}", {"capacity": 4}, format="json")

    assert response.status_code == 403


def test_404_for_room_in_other_tenant():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    room = _make_room(tenant_a, capacity=2, occupied_count=0, room_no="101")
    client = _auth_client(tenant_b, role="admin")

    response = client.patch(f"/api/v1/hostel/rooms/{room.id}", {"capacity": 4}, format="json")

    assert response.status_code == 404
