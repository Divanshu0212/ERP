"""Tests for Task 4.8: POST /api/v1/hostel/allocate.

This is the saga-start half of the hostel-allocation saga: it reserves a
room (increments occupied_count) and creates a pending Allocation in the
SAME transaction as the ``hostel.allocation.requested`` outbox event — the
transactional-outbox guarantee (state and event commit or roll back
together; nothing here talks to RabbitMQ directly, ``drain_outbox_task``
relays it later). ``select_for_update()`` on the Room row prevents
concurrent over-allocation under load.

Tokens are minted directly with pyjwt (``import jwt``) rather than going
through auth-service's login flow — hostel-service only ever *verifies*
JWTs (see suerp_common.auth.JWTAuthentication), so a token signed with the
same HS256 ``JWT_SIGNING_KEY`` and carrying the sub/role/tenant claims is
indistinguishable from one auth-service would have issued.
"""

import uuid

import jwt
import pytest
from django.conf import settings
from hostel.models import Allocation, Block, Room
from rest_framework.test import APIClient
from suerp_common.outbox import OutboxEvent

pytestmark = pytest.mark.django_db


def _make_token(tenant_id, user_id=None, role="warden"):
    claims = {
        "sub": str(user_id or uuid.uuid4()),
        "role": role,
        "tenant": str(tenant_id),
    }
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")


def _auth_client(tenant_id, **kwargs):
    client = APIClient()
    token = _make_token(tenant_id, **kwargs)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _make_block(tenant_id, gender_type="M"):
    return Block.all_objects.create(
        tenant_id=tenant_id,
        name="Block A",
        gender_type=gender_type,
        warden_id=uuid.uuid4(),
    )


def _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101"):
    block = _make_block(tenant_id)
    return Room.all_objects.create(
        tenant_id=tenant_id,
        block=block,
        room_no=room_no,
        capacity=capacity,
        occupied_count=occupied_count,
    )


def test_allocating_available_room_creates_pending_allocation_and_emits_event():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    student_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {"room_id": str(room.id), "student_id": str(student_id)},
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "pending"
    assert body["data"]["room_id"] == str(room.id)
    assert body["data"]["student_id"] == str(student_id)

    allocations = Allocation.all_objects.filter(room=room, student_id=student_id)
    assert allocations.count() == 1
    allocation = allocations.first()
    assert allocation.status == "pending"

    room.refresh_from_db()
    assert room.occupied_count == 1

    events = OutboxEvent.objects.filter(type="hostel.allocation.requested")
    assert events.count() == 1
    event = events.first()
    assert str(event.tenant_id) == str(tenant_id)
    assert event.payload == {
        "allocation_id": str(allocation.id),
        "student_id": str(student_id),
        "room_id": str(room.id),
    }


def test_allocating_full_room_returns_400_and_creates_nothing():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=2)
    student_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {"room_id": str(room.id), "student_id": str(student_id)},
        format="json",
    )

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert "capacity" in body["message"].lower()

    assert Allocation.all_objects.filter(room=room).count() == 0

    room.refresh_from_db()
    assert room.occupied_count == 2

    assert OutboxEvent.objects.filter(type="hostel.allocation.requested").count() == 0


def test_student_role_cannot_allocate():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    client = _auth_client(tenant_id, role="student")

    response = client.post(
        "/api/v1/hostel/allocate",
        {"room_id": str(room.id), "student_id": str(uuid.uuid4())},
        format="json",
    )

    assert response.status_code == 403
    assert Allocation.all_objects.filter(room=room).count() == 0
    assert OutboxEvent.objects.count() == 0


def test_warden_cannot_allocate_room_from_a_different_tenant():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    room = _make_room(tenant_a, capacity=2, occupied_count=0)
    client_b = _auth_client(tenant_b, role="warden")

    response = client_b.post(
        "/api/v1/hostel/allocate",
        {"room_id": str(room.id), "student_id": str(uuid.uuid4())},
        format="json",
    )

    assert response.status_code == 404

    room.refresh_from_db()
    assert room.occupied_count == 0
    assert Allocation.all_objects.filter(room=room).count() == 0
    assert OutboxEvent.objects.count() == 0


def test_available_rooms_lists_only_rooms_with_capacity_tenant_scoped():
    """GET /rooms/available filters at the DB level: full rooms and other
    tenants' rooms are excluded."""
    tenant_id = uuid.uuid4()
    other_tenant = uuid.uuid4()

    open_room = _make_room(tenant_id, capacity=2, occupied_count=1, room_no="201")
    _make_room(tenant_id, capacity=2, occupied_count=2, room_no="202")  # full -> excluded
    _make_room(other_tenant, capacity=2, occupied_count=0, room_no="203")  # other tenant

    client = _auth_client(tenant_id, role="student")
    response = client.get("/api/v1/hostel/rooms/available")

    assert response.status_code == 200
    results = response.data["data"]["results"]
    returned_ids = {r["id"] for r in results}
    assert returned_ids == {str(open_room.id)}
