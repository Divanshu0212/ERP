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

``fee_structure_id`` is optional. When omitted (falsy), this is a DIRECT
allocation: no fee, no invoice, no payment saga — the Allocation is created
already CONFIRMED and no event is published at all. ``hostel.allocation.
requested`` is consumed ONLY by finance-service, purely to trigger invoice
creation (verified: no other service subscribes to it), so there is
nothing for finance-service to do when there's no fee — publishing the
event and waiting for a saga that will never happen would just be a
pointless round trip through the event bus for something this function
already knows synchronously.

When ``fee_structure_id`` IS given, ``due_date`` is required alongside it
(enforced by callers — see hostel/views.py — not here, since the
both-or-neither validation differs slightly per call site's serializer).
``due_date`` is stamped onto the Allocation and flows into the event
payload so finance-service's consumer can stamp the same deadline onto its
Invoice. ``hostel.tasks.release_stale_pending_allocations`` uses
``Allocation.due_date`` (not finance-service's copy) to release an unpaid
allocation once its deadline passes.
"""

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from hostel.models import Allocation, Room
from suerp_common.outbox import publish_event


class RoomFullError(Exception):
    """Raised when the target room has no free capacity."""


class StudentAlreadyAllocatedError(Exception):
    """Raised when student_user_code already holds a pending/confirmed
    allocation (allocation_one_active_per_student constraint)."""


def create_allocation(
    room_id,
    student_user_code,
    tenant_id,
    fee_structure_id=None,
    university_name="",
    due_date=None,
) -> Allocation:
    """Reserve a room seat and create an Allocation for student_user_code.

    Raises ``django.http.Http404`` if room_id doesn't resolve to a room in
    this tenant, ``RoomFullError`` if the room has no free capacity,
    ``StudentAlreadyAllocatedError`` if the student already holds an active
    (pending/confirmed) allocation anywhere.
    """
    try:
        with transaction.atomic():
            room = get_object_or_404(Room.objects.select_for_update(), id=room_id)

            if not room.is_available:
                raise RoomFullError(f"Room {room_id} is at full capacity.")

            initial_status = (
                Allocation.Status.PENDING if fee_structure_id else Allocation.Status.CONFIRMED
            )
            allocation = Allocation.objects.create(
                tenant_id=tenant_id,
                room=room,
                student_user_code=student_user_code,
                status=initial_status,
                due_date=due_date if fee_structure_id else None,
            )

            room.occupied_count += 1
            room.save(update_fields=["occupied_count"])

            if fee_structure_id:
                publish_event(
                    "hostel.allocation.requested",
                    tenant_id=tenant_id,
                    payload={
                        "allocation_id": str(allocation.id),
                        "student_user_code": allocation.student_user_code,
                        "room_id": str(room.id),
                        "fee_structure_id": str(fee_structure_id),
                        "university_name": university_name,
                        "due_date": str(due_date),
                    },
                )

            return allocation
    except IntegrityError as exc:
        raise StudentAlreadyAllocatedError(
            f"{student_user_code} already holds an active allocation."
        ) from exc
