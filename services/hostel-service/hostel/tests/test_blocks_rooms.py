"""POST/GET /api/v1/hostel/blocks and /api/v1/hostel/rooms — hostel setup.

Without these, the only way to create a Room/Block is direct DB access
(fixtures/migrations/admin shell) — there is no API for it at all today.
"""

import uuid
from unittest.mock import patch

import pytest
from hostel.models import Block, Room

pytestmark = pytest.mark.django_db

from hostel.tests.test_allocate import _auth_client, _make_block  # noqa: E402


@patch("hostel.views.resolve_user_by_code")
def test_admin_creates_block(mock_resolve):
    tenant_id = uuid.uuid4()
    warden_user_code = "WARD-1"
    mock_resolve.return_value = {
        "user_code": warden_user_code,
        "email": "warden@example.com",
        "role": "warden",
    }
    client = _auth_client(tenant_id, role="admin")

    response = client.post(
        "/api/v1/hostel/blocks",
        {"name": "Block C", "gender_type": "F", "warden_user_code": warden_user_code},
        format="json",
    )

    assert response.status_code == 201, response.content
    data = response.json()["data"]
    assert data["name"] == "Block C"
    assert data["warden_id"] == warden_user_code
    assert Block.all_objects.filter(tenant_id=tenant_id, name="Block C").exists()


def test_warden_cannot_create_block():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/blocks",
        {"name": "Block C", "gender_type": "F", "warden_user_code": "WARD-1"},
        format="json",
    )

    assert response.status_code == 403


@patch("hostel.views.resolve_user_by_code")
def test_create_block_400_when_warden_code_not_found(mock_resolve):
    from hostel.lookups import LookupFailed

    tenant_id = uuid.uuid4()
    mock_resolve.side_effect = LookupFailed("not_found", "No user found.")
    client = _auth_client(tenant_id, role="admin")

    response = client.post(
        "/api/v1/hostel/blocks",
        {"name": "Block C", "gender_type": "F", "warden_user_code": "WARD-999"},
        format="json",
    )

    assert response.status_code == 400
    assert Block.all_objects.count() == 0


def test_list_blocks_is_tenant_scoped():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    _make_block(tenant_a)
    _make_block(tenant_b)
    client = _auth_client(tenant_a, role="admin")

    response = client.get("/api/v1/hostel/blocks")

    assert response.status_code == 200
    assert len(response.json()["data"]["results"]) == 1


def test_admin_creates_room():
    tenant_id = uuid.uuid4()
    block = _make_block(tenant_id)
    client = _auth_client(tenant_id, role="admin")

    response = client.post(
        "/api/v1/hostel/rooms",
        {"block_id": str(block.id), "room_no": "303", "capacity": 3},
        format="json",
    )

    assert response.status_code == 201, response.content
    data = response.json()["data"]
    assert data["room_no"] == "303"
    assert data["block_name"] == block.name
    assert Room.all_objects.filter(tenant_id=tenant_id, room_no="303").exists()


def test_warden_can_also_create_room():
    tenant_id = uuid.uuid4()
    block = _make_block(tenant_id)
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/rooms",
        {"block_id": str(block.id), "room_no": "304"},
        format="json",
    )

    assert response.status_code == 201, response.content


def test_student_cannot_create_room():
    tenant_id = uuid.uuid4()
    block = _make_block(tenant_id)
    client = _auth_client(tenant_id, role="student")

    response = client.post(
        "/api/v1/hostel/rooms",
        {"block_id": str(block.id), "room_no": "305"},
        format="json",
    )

    assert response.status_code == 403


def test_create_room_404_for_block_in_other_tenant():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    block = _make_block(tenant_a)
    client = _auth_client(tenant_b, role="admin")

    response = client.post(
        "/api/v1/hostel/rooms",
        {"block_id": str(block.id), "room_no": "306"},
        format="json",
    )

    assert response.status_code == 404


def test_list_rooms_includes_block_name():
    tenant_id = uuid.uuid4()
    block = _make_block(tenant_id)
    Room.all_objects.create(tenant_id=tenant_id, block=block, room_no="401", capacity=2)
    client = _auth_client(tenant_id, role="admin")

    response = client.get("/api/v1/hostel/rooms")

    assert response.status_code == 200
    results = response.json()["data"]["results"]
    assert results[0]["block_name"] == block.name
