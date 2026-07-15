"""DB-level constraints on Allocation:
- allocation_one_active_per_student: a student can hold at most one
  pending/confirmed allocation at a time, across any room. A released
  allocation doesn't count, so the student can be reallocated later.
"""

import uuid

import pytest
from django.db import IntegrityError
from hostel.models import Allocation

pytestmark = pytest.mark.django_db

from hostel.tests.test_allocate import _make_room  # noqa: E402


def _make_allocation(tenant_id, room, student_user_code, status="pending"):
    return Allocation.all_objects.create(
        tenant_id=tenant_id,
        room=room,
        student_user_code=student_user_code,
        status=status,
    )


def test_rejects_second_pending_allocation_for_same_student():
    tenant_id = uuid.uuid4()
    room_a = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    room_b = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="102")
    _make_allocation(tenant_id, room_a, "STU001", status="pending")

    with pytest.raises(IntegrityError):
        _make_allocation(tenant_id, room_b, "STU001", status="pending")


def test_rejects_confirmed_and_pending_combination():
    tenant_id = uuid.uuid4()
    room_a = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    room_b = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="102")
    _make_allocation(tenant_id, room_a, "STU001", status="confirmed")

    with pytest.raises(IntegrityError):
        _make_allocation(tenant_id, room_b, "STU001", status="pending")


def test_allows_new_allocation_after_release():
    tenant_id = uuid.uuid4()
    room_a = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    room_b = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="102")
    _make_allocation(tenant_id, room_a, "STU001", status="released")

    # Should not raise.
    _make_allocation(tenant_id, room_b, "STU001", status="pending")


def test_due_date_field_defaults_to_none():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    allocation = _make_allocation(tenant_id, room, "STU001", status="pending")

    assert allocation.due_date is None
