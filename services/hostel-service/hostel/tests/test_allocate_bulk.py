"""POST /api/v1/hostel/allocate/bulk — CSV/XLSX bulk allocation.

Each row is processed independently (its own try/except around
create_allocation), so a bad row never aborts the batch — the response and
the persisted AllocationImportBatch/Row log always report a mix of
success/fail counts.
"""

import io
import uuid
from unittest.mock import patch

import openpyxl
import pytest
from hostel.models import Allocation, AllocationImportBatch

pytestmark = pytest.mark.django_db

from hostel.tests.test_allocate import _auth_client, _make_room  # noqa: E402


def _csv_file(rows, filename="import.csv"):
    """rows: list of (room_id, student_user_code) 2-tuples OR
    (room_id, student_user_code, fee_structure_id, due_date) 4-tuples."""
    lines = ["room_id,student_user_code,fee_structure_id,due_date"]
    for r in rows:
        if len(r) == 2:
            r = (r[0], r[1], "", "")
        lines.append(",".join(r))
    content = "\n".join(lines).encode("utf-8")
    return io.BytesIO(content), filename


def _xlsx_file(rows, filename="import.xlsx"):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["room_id", "student_user_code", "fee_structure_id", "due_date"])
    for r in rows:
        if len(r) == 2:
            r = (r[0], r[1], "", "")
        sheet.append(list(r))
    buf = io.BytesIO()
    workbook.save(buf)
    buf.seek(0)
    return buf, filename


def _upload(client, buf, filename):
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile(filename, buf.read())
    return client.post("/api/v1/hostel/allocate/bulk", {"file": upload}, format="multipart")


@patch("hostel.views.resolve_user_by_code")
def test_all_rows_succeed_csv(mock_resolve):
    tenant_id = uuid.uuid4()
    room1 = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    room2 = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="102")
    mock_resolve.side_effect = lambda user_code, auth: {
        "user_code": user_code,
        "email": f"{user_code.lower()}@example.com",
        "role": "student",
    }
    client = _auth_client(tenant_id, role="warden")

    buf, name = _csv_file([(str(room1.id), "STU-1"), (str(room2.id), "STU-2")])
    response = _upload(client, buf, name)

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["total_rows"] == 2
    assert body["success_count"] == 2
    assert body["fail_count"] == 0

    batch = AllocationImportBatch.all_objects.get(id=body["batch_id"])
    assert batch.filename == name
    assert batch.rows.filter(status="success").count() == 2
    assert Allocation.all_objects.filter(tenant_id=tenant_id).count() == 2


@patch("hostel.views.resolve_user_by_code")
def test_all_rows_succeed_xlsx(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    mock_resolve.return_value = {
        "user_code": "STU-1",
        "email": "a@example.com",
        "role": "student",
    }
    client = _auth_client(tenant_id, role="warden")

    buf, name = _xlsx_file([(str(room.id), "STU-1")])
    response = _upload(client, buf, name)

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["success_count"] == 1
    assert body["fail_count"] == 0


@patch("hostel.views.resolve_user_by_code")
def test_mixed_success_and_failure(mock_resolve):
    from hostel.lookups import LookupFailed

    tenant_id = uuid.uuid4()
    good_room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    full_room = _make_room(tenant_id, capacity=1, occupied_count=1, room_no="102")

    def resolve_side_effect(user_code, auth):
        if user_code == "STU-UNKNOWN":
            raise LookupFailed("not_found", "No user found.")
        return {"user_code": user_code, "email": f"{user_code.lower()}@example.com", "role": "student"}

    mock_resolve.side_effect = resolve_side_effect
    client = _auth_client(tenant_id, role="warden")

    buf, name = _csv_file(
        [
            (str(good_room.id), "STU-GOOD"),
            (str(full_room.id), "STU-2"),
            ("not-a-uuid", "STU-3"),
            (str(good_room.id), "STU-UNKNOWN"),
        ]
    )
    response = _upload(client, buf, name)

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["total_rows"] == 4
    assert body["success_count"] == 1
    assert body["fail_count"] == 3

    batch = AllocationImportBatch.all_objects.get(id=body["batch_id"])
    rows = list(batch.rows.order_by("row_number"))
    assert rows[0].status == "success"
    assert rows[1].status == "failed" and "capacity" in rows[1].error_message.lower()
    assert rows[2].status == "failed"
    assert rows[3].status == "failed" and "no user found" in rows[3].error_message.lower()


@patch("hostel.views.resolve_user_by_code")
def test_blank_code_row_is_skipped_not_failed(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    mock_resolve.return_value = {
        "user_code": "STU-1",
        "email": "a@example.com",
        "role": "student",
    }
    client = _auth_client(tenant_id, role="warden")

    buf, name = _csv_file([(str(room.id), "")])
    response = _upload(client, buf, name)

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["total_rows"] == 1
    assert body["success_count"] == 0
    assert body["fail_count"] == 0
    assert body["skipped_count"] == 1

    batch = AllocationImportBatch.all_objects.get(id=body["batch_id"])
    row = batch.rows.get(row_number=1)
    assert row.status == "skipped"
    assert "no user_code" in row.error_message.lower()


def test_rejects_wrong_extension():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="warden")

    buf, name = _csv_file([(str(uuid.uuid4()), "STU-1")], filename="import.txt")
    response = _upload(client, buf, name)

    assert response.status_code == 415
    assert AllocationImportBatch.all_objects.count() == 0


def test_rejects_missing_columns():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="warden")

    content = io.BytesIO(b"foo,bar\n1,2\n")
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("import.csv", content.read())
    response = client.post("/api/v1/hostel/allocate/bulk", {"file": upload}, format="multipart")

    assert response.status_code == 400
    assert AllocationImportBatch.all_objects.count() == 0


def test_student_role_cannot_bulk_allocate():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="student")

    buf, name = _csv_file([(str(uuid.uuid4()), "STU-1")])
    response = _upload(client, buf, name)

    assert response.status_code == 403
    assert AllocationImportBatch.all_objects.count() == 0


@patch("hostel.views.resolve_user_by_code")
def test_same_student_twice_in_batch_fails_second_row_not_whole_batch(mock_resolve):
    """The one-seat-per-student constraint must reject a duplicate user_code
    on a later row as a per-row failure (StudentAlreadyAllocatedError caught),
    not crash the batch or silently double-allocate the student — this is the
    exact CSV copy-paste bug the constraint was added to close."""
    tenant_id = uuid.uuid4()
    room1 = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    room2 = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="102")
    mock_resolve.side_effect = lambda user_code, auth: {
        "user_code": user_code,
        "email": f"{user_code.lower()}@example.com",
        "role": "student",
    }
    client = _auth_client(tenant_id, role="warden")

    buf, name = _csv_file([(str(room1.id), "STU-DUP"), (str(room2.id), "STU-DUP")])
    response = _upload(client, buf, name)

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["success_count"] == 1
    assert body["fail_count"] == 1

    batch = AllocationImportBatch.all_objects.get(id=body["batch_id"])
    rows = list(batch.rows.order_by("row_number"))
    assert rows[0].status == "success"
    assert rows[1].status == "failed"
    assert "already holds an active allocation" in rows[1].error_message.lower()

    assert Allocation.all_objects.filter(tenant_id=tenant_id, student_user_code="STU-DUP").count() == 1
    room2.refresh_from_db()
    assert room2.occupied_count == 0  # failed row's seat reservation rolled back


@patch("hostel.views.resolve_user_by_code")
def test_different_students_same_room_both_succeed(mock_resolve):
    """The one-seat constraint is keyed on student, not room — two different
    students allocated into the same (multi-capacity) room in one batch must
    both succeed."""
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    mock_resolve.side_effect = lambda user_code, auth: {
        "user_code": user_code,
        "email": f"{user_code.lower()}@example.com",
        "role": "student",
    }
    client = _auth_client(tenant_id, role="warden")

    buf, name = _csv_file([(str(room.id), "STU-A"), (str(room.id), "STU-B")])
    response = _upload(client, buf, name)

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["success_count"] == 2
    assert body["fail_count"] == 0

    assert Allocation.all_objects.filter(tenant_id=tenant_id, room=room).count() == 2
    room.refresh_from_db()
    assert room.occupied_count == 2


@patch("hostel.views.resolve_user_by_code")
def test_past_due_date_row_fails_without_aborting_batch(mock_resolve):
    tenant_id = uuid.uuid4()
    good_room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    bad_room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="102")
    mock_resolve.side_effect = lambda user_code, auth: {
        "user_code": user_code,
        "email": f"{user_code.lower()}@example.com",
        "role": "student",
    }
    client = _auth_client(tenant_id, role="warden")

    fee_id = str(uuid.uuid4())
    buf, name = _csv_file(
        [
            (str(good_room.id), "STU-1"),
            (str(bad_room.id), "STU-2", fee_id, "2020-01-01"),
        ]
    )
    response = _upload(client, buf, name)

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["success_count"] == 1
    assert body["fail_count"] == 1

    batch = AllocationImportBatch.all_objects.get(id=body["batch_id"])
    rows = list(batch.rows.order_by("row_number"))
    assert rows[0].status == "success"
    assert rows[1].status == "failed"
    assert "future" in rows[1].error_message.lower()
