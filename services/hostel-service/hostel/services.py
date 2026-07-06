"""Allocation creation, shared by the single-create and bulk-import
endpoints (hostel/views.py: AllocateView, AllocateBulkView) and by
room-request approval (hostel/views.py: ApproveRoomRequestView).

Extracted from AllocateView (Task 4.8) unchanged, so every caller reuses the
exact same lock/capacity-check/atomic-commit/outbox logic per allocation
instead of duplicating it. ``select_for_update()`` on the Room row prevents
concurrent over-allocation: two simultaneous calls against the same
last-open bed serialize on the row lock, so the second one observes the
incremented ``occupied_count`` and correctly raises ``RoomFullError``
instead of double-booking. State change and the ``hostel.allocation.
requested`` outbox event commit or roll back together (transactional-
outbox guarantee) — nothing here talks to RabbitMQ directly,
``drain_outbox_task`` relays it later.

``fee_structure_id``/``university_name`` are optional, warden-approval-only
extras: they flow straight into the outbox event payload so finance-
service's consumer can price the resulting invoice from a configurable
``FeeStructure`` and stamp the institution's display name onto it, instead
of the old hardcoded ``HOSTEL_FEE_AMOUNT`` constant. Callers that don't pass
them (the plain warden AllocateView/AllocateBulkView path) get ``None``/``""``,
and finance-service's consumer falls back to its existing hardcoded default
in that case — see Task 4.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from hostel.models import Allocation, Room
from suerp_common.outbox import publish_event


class RoomFullError(Exception):
    """Raised when the target room has no free capacity."""


def create_allocation(
    room_id,
    student_id,
    tenant_id,
    fee_structure_id=None,
    university_name="",
) -> Allocation:
    """Reserve a room seat and create a pending Allocation for student_id.

    Raises ``django.http.Http404`` if room_id doesn't resolve to a room in
    this tenant (via get_object_or_404, matching the pre-refactor
    behavior), ``RoomFullError`` if the room has no free capacity.
    """
    with transaction.atomic():
        room = get_object_or_404(Room.objects.select_for_update(), id=room_id)

        if not room.is_available:
            raise RoomFullError(f"Room {room_id} is at full capacity.")

        allocation = Allocation.objects.create(
            tenant_id=tenant_id,
            room=room,
            student_id=student_id,
            status=Allocation.Status.PENDING,
        )

        room.occupied_count += 1
        room.save(update_fields=["occupied_count"])

        publish_event(
            "hostel.allocation.requested",
            tenant_id=tenant_id,
            payload={
                "allocation_id": str(allocation.id),
                "student_id": str(allocation.student_id),
                "room_id": str(room.id),
                "fee_structure_id": str(fee_structure_id) if fee_structure_id else None,
                "university_name": university_name,
            },
        )

        return allocation
