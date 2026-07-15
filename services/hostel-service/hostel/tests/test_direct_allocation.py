"""create_allocation() with no fee_structure_id: confirms synchronously,
no hostel.allocation.requested event published, finance-service never
involved. With fee_structure_id: unchanged saga behavior, but due_date is
now stamped onto the Allocation and included in the event payload.
"""

import uuid

import pytest
from hostel.models import Allocation
from hostel.services import StudentAlreadyAllocatedError, create_allocation
from suerp_common.outbox import OutboxEvent

pytestmark = pytest.mark.django_db

from hostel.tests.test_allocate import _make_room  # noqa: E402


def test_no_fee_confirms_immediately_no_event():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")

    allocation = create_allocation(room.id, "STU001", tenant_id)

    assert allocation.status == Allocation.Status.CONFIRMED
    assert allocation.due_date is None
    assert not OutboxEvent.objects.filter(
        tenant_id=tenant_id, type="hostel.allocation.requested"
    ).exists()

    room.refresh_from_db()
    assert room.occupied_count == 1


def test_fee_with_due_date_stays_pending_and_publishes_event():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    fee_structure_id = uuid.uuid4()
    due_date = "2026-08-01"

    allocation = create_allocation(
        room.id,
        "STU001",
        tenant_id,
        fee_structure_id=fee_structure_id,
        due_date=due_date,
    )

    assert allocation.status == Allocation.Status.PENDING
    assert str(allocation.due_date) == due_date

    event = OutboxEvent.objects.get(tenant_id=tenant_id, type="hostel.allocation.requested")
    assert event.payload["fee_structure_id"] == str(fee_structure_id)
    assert event.payload["due_date"] == due_date


def test_second_allocation_for_same_student_raises():
    tenant_id = uuid.uuid4()
    room_a = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    room_b = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="102")
    create_allocation(room_a.id, "STU001", tenant_id)

    with pytest.raises(StudentAlreadyAllocatedError):
        create_allocation(room_b.id, "STU001", tenant_id)

    # Room b's seat must NOT have been consumed by the failed attempt.
    room_b.refresh_from_db()
    assert room_b.occupied_count == 0
