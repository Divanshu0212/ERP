"""GET /api/v1/hostel/allocations/import-logs[/<id>] — bulk-import audit trail."""

import uuid

import pytest
from hostel.models import AllocationImportBatch, AllocationImportRow

pytestmark = pytest.mark.django_db

from hostel.tests.test_allocate import _auth_client  # noqa: E402


def _make_batch(tenant_id, filename="import.csv", total=2, success=1, fail=1):
    return AllocationImportBatch.all_objects.create(
        tenant_id=tenant_id,
        uploaded_by="WARD-1",
        filename=filename,
        total_rows=total,
        success_count=success,
        fail_count=fail,
    )


def test_list_returns_tenant_scoped_batches():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    _make_batch(tenant_a, filename="a.csv")
    _make_batch(tenant_b, filename="b.csv")
    client = _auth_client(tenant_a, role="warden")

    response = client.get("/api/v1/hostel/allocations/import-logs")

    assert response.status_code == 200
    results = response.json()["data"]["results"]
    assert [r["filename"] for r in results] == ["a.csv"]


def test_detail_includes_rows():
    tenant_id = uuid.uuid4()
    batch = _make_batch(tenant_id)
    AllocationImportRow.all_objects.create(
        tenant_id=tenant_id,
        batch=batch,
        row_number=1,
        room_id_raw=str(uuid.uuid4()),
        student_user_code_raw="STU-1",
        status=AllocationImportRow.Status.SUCCESS,
    )
    AllocationImportRow.all_objects.create(
        tenant_id=tenant_id,
        batch=batch,
        row_number=2,
        room_id_raw="bad",
        student_user_code_raw="STU-2",
        status=AllocationImportRow.Status.FAILED,
        error_message="Room not found.",
    )
    client = _auth_client(tenant_id, role="warden")

    response = client.get(f"/api/v1/hostel/allocations/import-logs/{batch.id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["filename"] == batch.filename
    assert len(data["rows"]) == 2
    assert data["rows"][1]["error_message"] == "Room not found."


def test_detail_404_for_other_tenant():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    batch = _make_batch(tenant_a)
    client = _auth_client(tenant_b, role="warden")

    response = client.get(f"/api/v1/hostel/allocations/import-logs/{batch.id}")

    assert response.status_code == 404


def test_student_role_cannot_view_logs():
    tenant_id = uuid.uuid4()
    _make_batch(tenant_id)
    client = _auth_client(tenant_id, role="student")

    response = client.get("/api/v1/hostel/allocations/import-logs")

    assert response.status_code == 403
