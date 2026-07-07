"""Model tests for Task 4.7: Block, Room, Allocation, LeaveRequest, Complaint.

Room/Allocation/etc. are all suerp_common.tenancy.TenantModel subclasses —
this proves tenant isolation (objects vs all_objects) works on hostel-
service's own models, plus Room.is_available and the Block<->Room<->
Allocation relations.
"""

import uuid

import pytest
from hostel.models import Allocation, AllocationImportBatch, AllocationImportRow, Block, Room
from suerp_common.tenancy import set_current_tenant

pytestmark = pytest.mark.django_db


def _make_block(tenant_id, gender_type="M"):
    return Block.all_objects.create(
        tenant_id=tenant_id,
        name="Block A",
        gender_type=gender_type,
        warden_id="WARD-1",
    )


def _make_room(tenant_id, block=None, capacity=2, occupied_count=0, room_no="101"):
    block = block or _make_block(tenant_id)
    return Room.all_objects.create(
        tenant_id=tenant_id,
        block=block,
        room_no=room_no,
        capacity=capacity,
        occupied_count=occupied_count,
    )


def test_room_is_available_true_when_occupied_below_capacity():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1)
    assert room.is_available is True


def test_room_is_available_false_when_at_capacity():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=2)
    assert room.is_available is False


def test_allocation_tenant_scoping_isolates_by_tenant():
    """Two allocations created under different tenant_ids: with tenant
    context set to A, `Allocation.objects` returns only A's allocation while
    `all_objects` (unscoped) returns both."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    room_a = _make_room(tenant_a)
    room_b = _make_room(tenant_b)

    allocation_a = Allocation.all_objects.create(
        tenant_id=tenant_a,
        room=room_a,
        student_user_code="STU-A",
    )
    allocation_b = Allocation.all_objects.create(
        tenant_id=tenant_b,
        room=room_b,
        student_user_code="STU-B",
    )

    try:
        set_current_tenant(str(tenant_a))
        scoped = list(Allocation.objects.all())
        assert scoped == [allocation_a]

        unscoped = set(Allocation.all_objects.all())
        assert unscoped == {allocation_a, allocation_b}
    finally:
        set_current_tenant(None)


def test_allocation_default_status_is_pending():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id)
    allocation = Allocation.all_objects.create(
        tenant_id=tenant_id,
        room=room,
        student_user_code="STU-1",
    )
    assert allocation.status == "pending"


def test_room_attaches_to_block():
    tenant_id = uuid.uuid4()
    block = _make_block(tenant_id)
    _make_room(tenant_id, block=block)
    assert block.rooms.count() == 1


def test_import_batch_and_row_creation():
    tenant_id = uuid.uuid4()
    block = Block.all_objects.create(
        tenant_id=tenant_id, name="Block A", gender_type="M", warden_id="WARD-1"
    )
    room = Room.all_objects.create(tenant_id=tenant_id, block=block, room_no="101", capacity=2)
    allocation = Allocation.all_objects.create(
        tenant_id=tenant_id, room=room, student_user_code="STU-1", status=Allocation.Status.PENDING
    )

    batch = AllocationImportBatch.all_objects.create(
        tenant_id=tenant_id,
        uploaded_by="WARD-1",
        filename="import.csv",
        total_rows=2,
        success_count=1,
        fail_count=1,
    )
    success_row = AllocationImportRow.all_objects.create(
        tenant_id=tenant_id,
        batch=batch,
        row_number=1,
        room_id_raw=str(room.id),
        student_user_code_raw="STU-1",
        status=AllocationImportRow.Status.SUCCESS,
        allocation=allocation,
    )
    failed_row = AllocationImportRow.all_objects.create(
        tenant_id=tenant_id,
        batch=batch,
        row_number=2,
        room_id_raw="not-a-uuid",
        student_user_code_raw="STU-2",
        status=AllocationImportRow.Status.FAILED,
        error_message="Room not found.",
    )

    assert list(batch.rows.order_by("row_number")) == [success_row, failed_row]
    assert success_row.allocation_id == allocation.id
    assert failed_row.allocation is None
