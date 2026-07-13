"""GET /api/v1/hostel/rooms/available-template — CSV download of available rooms,
pre-filled with room_id and room_name so a warden can fill in student_user_code and
re-upload it directly to /api/v1/hostel/allocate/bulk.
"""

import csv
import io
import uuid

import pytest

pytestmark = pytest.mark.django_db

from hostel.models import Room  # noqa: E402
from hostel.tests.test_allocate import _auth_client, _make_block, _make_room  # noqa: E402


def test_returns_one_row_per_free_seat():
    tenant_id = uuid.uuid4()
    available = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    partially_full = _make_room(tenant_id, capacity=3, occupied_count=2, room_no="103")
    full = _make_room(tenant_id, capacity=1, occupied_count=1, room_no="102")
    client = _auth_client(tenant_id, role="warden")

    response = client.get("/api/v1/hostel/rooms/available-template")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]

    content = response.content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    assert reader.fieldnames == ["room_id", "room_name", "student_user_code"]
    rows = list(reader)

    available_rows = [r for r in rows if r["room_id"] == str(available.id)]
    assert len(available_rows) == 2
    for row in available_rows:
        assert row["room_name"] == f"{available.block.name} - {available.room_no}"
        assert row["student_user_code"] == ""

    partial_rows = [r for r in rows if r["room_id"] == str(partially_full.id)]
    assert len(partial_rows) == 1

    assert str(full.id) not in content


def test_ordered_by_block_then_room_no():
    tenant_id = uuid.uuid4()
    block_a = _make_block(tenant_id)
    block_a.name = "Block A"
    block_a.save(update_fields=["name"])
    room_b2 = Room.all_objects.create(
        tenant_id=tenant_id, block=block_a, room_no="B2", capacity=1, occupied_count=0
    )
    room_a1 = Room.all_objects.create(
        tenant_id=tenant_id, block=block_a, room_no="A1", capacity=1, occupied_count=0
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
