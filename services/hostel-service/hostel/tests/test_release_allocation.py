"""POST /api/v1/hostel/allocations/<id>/release — warden manually releases an
allocation (student moved out, mistake, etc.), independent of the automated
payment-saga release path in hostel/consumers.py. Frees the room seat the
same way (occupied_count -= 1, status -> released) but triggered directly
by a warden/admin instead of a payment-failed/timeout event.
"""

import uuid

import pytest

pytestmark = pytest.mark.django_db

from hostel.models import Allocation  # noqa: E402
from hostel.tests.test_allocate import _auth_client, _make_room  # noqa: E402
from suerp_common.outbox import OutboxEvent  # noqa: E402


def _make_allocation(tenant_id, room, student_user_code="STU001", status="confirmed"):
    return Allocation.all_objects.create(
        tenant_id=tenant_id,
        room=room,
        student_user_code=student_user_code,
        status=status,
    )


def test_warden_releases_confirmed_allocation_frees_seat():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1, room_no="101")
    allocation = _make_allocation(tenant_id, room, status="confirmed")
    client = _auth_client(tenant_id, role="warden")

    response = client.post(f"/api/v1/hostel/allocations/{allocation.id}/release")

    assert response.status_code == 200, response.content
    body = response.json()["data"]
    assert body["status"] == "released"

    allocation.refresh_from_db()
    assert allocation.status == "released"
    room.refresh_from_db()
    assert room.occupied_count == 0

    event = OutboxEvent.objects.get(tenant_id=tenant_id, type="hostel.allocation.released")
    assert event.payload["allocation_id"] == str(allocation.id)
    assert event.payload["room_id"] == str(room.id)


def test_warden_releases_pending_allocation():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1, room_no="101")
    allocation = _make_allocation(tenant_id, room, status="pending")
    client = _auth_client(tenant_id, role="warden")

    response = client.post(f"/api/v1/hostel/allocations/{allocation.id}/release")

    assert response.status_code == 200, response.content
    allocation.refresh_from_db()
    assert allocation.status == "released"
    room.refresh_from_db()
    assert room.occupied_count == 0


def test_admin_can_also_release():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1, room_no="101")
    allocation = _make_allocation(tenant_id, room, status="confirmed")
    client = _auth_client(tenant_id, role="admin")

    response = client.post(f"/api/v1/hostel/allocations/{allocation.id}/release")

    assert response.status_code == 200, response.content


def test_rejects_already_released_allocation():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    allocation = _make_allocation(tenant_id, room, status="released")
    client = _auth_client(tenant_id, role="warden")

    response = client.post(f"/api/v1/hostel/allocations/{allocation.id}/release")

    assert response.status_code == 400
    room.refresh_from_db()
    assert room.occupied_count == 0  # unchanged, no double-decrement


def test_student_forbidden_from_releasing():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1, room_no="101")
    allocation = _make_allocation(tenant_id, room, status="confirmed")
    client = _auth_client(tenant_id, role="student", user_id="STU001")

    response = client.post(f"/api/v1/hostel/allocations/{allocation.id}/release")

    assert response.status_code == 403


def test_404_for_allocation_in_other_tenant():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    room = _make_room(tenant_a, capacity=2, occupied_count=1, room_no="101")
    allocation = _make_allocation(tenant_a, room, status="confirmed")
    client = _auth_client(tenant_b, role="warden")

    response = client.post(f"/api/v1/hostel/allocations/{allocation.id}/release")

    assert response.status_code == 404
