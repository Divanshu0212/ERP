"""GET /api/v1/hostel/rooms/available-template — CSV download of available rooms,
pre-filled with room_id and room_name so a warden can fill in student_email and
re-upload it directly to /api/v1/hostel/allocate/bulk.
"""

import csv
import io
import uuid

import pytest

pytestmark = pytest.mark.django_db

from hostel.models import Room
from hostel.tests.test_allocate import _auth_client, _make_block, _make_room  # noqa: E402


def test_returns_only_available_rooms_as_csv():
    tenant_id = uuid.uuid4()
    available = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    full = _make_room(tenant_id, capacity=1, occupied_count=1, room_no="102")
    client = _auth_client(tenant_id, role="warden")

    response = client.get("/api/v1/hostel/rooms/available-template")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]

    content = response.content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    assert reader.fieldnames == ["room_id", "room_name", "student_email"]
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["room_id"] == str(available.id)
    assert rows[0]["room_name"] == f"{available.block.name} - {available.room_no}"
    assert rows[0]["student_email"] == ""
    assert str(full.id) not in content


def test_ordered_by_block_then_room_no():
    tenant_id = uuid.uuid4()
    block_a = _make_block(tenant_id)
    block_a.name = "Block A"
    block_a.save(update_fields=["name"])
    room_b2 = Room.all_objects.create(
        tenant_id=tenant_id, block=block_a, room_no="B2", capacity=2, occupied_count=0
    )
    room_a1 = Room.all_objects.create(
        tenant_id=tenant_id, block=block_a, room_no="A1", capacity=2, occupied_count=0
    )
    client = _auth_client(tenant_id, role="warden")

    response = client.get("/api/v1/hostel/rooms/available-template")
    content = response.content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    room_ids_in_order = [row["room_id"] for row in reader]

    assert room_ids_in_order == [str(room_a1.id), str(room_b2.id)]


def test_student_role_forbidden():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="student")

    response = client.get("/api/v1/hostel/rooms/available-template")

    assert response.status_code == 403
