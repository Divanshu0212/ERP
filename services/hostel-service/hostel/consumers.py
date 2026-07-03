"""Event consumers (Task 4.9) — the saga steps that CLOSE the hostel
allocation saga.

hostel-service STARTED the saga (Task 4.8, ``AllocateView`` ->
``hostel.allocation.requested``) and finance-service reacted to that once
already (Task 4.5, see services/finance-service/billing/consumers.py: creates
a pending hostel-fee Invoice and emits ``finance.invoice.created``). This
module reacts to finance-service's next two possible outcomes — payment
succeeds or fails — and to a timeout when neither happens (see
``hostel.tasks.release_stale_pending_allocations``), closing the loop:

1. ``handle_invoice_created`` — a *correlation* step, not a saga outcome.
   ``finance.payment.success``/``finance.payment.failed`` payloads carry only
   ``invoice_id`` (not ``allocation_id`` — finance-service doesn't know or
   care about hostel's allocation concept once the invoice exists). But
   ``finance.invoice.created`` DOES carry both ``invoice_id`` and
   ``allocation_id``, so this handler stamps ``Allocation.invoice_id`` at that
   point, giving the later handlers a way to find the allocation again by
   ``invoice_id`` alone.
2. ``handle_payment_success`` — confirms the Allocation and emits
   ``hostel.allocation.confirmed``.
3. ``handle_payment_failed`` — the compensating action: releases the
   Allocation and frees the room seat (``occupied_count -= 1``).

This module follows the same three points as the reference consumer pattern
in services/finance-service/billing/consumers.py:

1. ``@idempotent`` (suerp_common.inbox) outermost on every handler — at-least
   -once delivery means duplicates happen, and each is recorded in
   ``ProcessedEvent`` so replays are a no-op.
2. Tenant resolved explicitly from ``event["tenant_id"]`` and all queries use
   ``Allocation.all_objects``/``Room.all_objects`` — consumers run as a
   standalone process (``manage.py consume_events``), never inside a Django
   request, so there's no ambient tenant for the auto-scoping
   ``TenantManager`` to filter by.
3. State change + ``publish_event`` in the SAME ``transaction.atomic()`` —
   the transactional outbox guarantee.

``select_for_update()`` on the Room row when decrementing ``occupied_count``
prevents lost updates under concurrent releases/allocations of the same room.
"""

import logging

from django.db import transaction
from hostel.models import Allocation, Room
from suerp_common.inbox import idempotent
from suerp_common.outbox import publish_event

logger = logging.getLogger(__name__)


def _release_allocation(allocation: Allocation) -> None:
    """Release ``allocation`` and free its room seat, under a row lock.

    Caller is expected to be inside a ``transaction.atomic()`` block.
    """
    room = Room.all_objects.select_for_update().get(pk=allocation.room_id)
    allocation.status = Allocation.Status.RELEASED
    allocation.save(update_fields=["status"])
    room.occupied_count = max(0, room.occupied_count - 1)
    room.save(update_fields=["occupied_count"])


@idempotent
def handle_invoice_created(event: dict) -> None:
    """Handle ``finance.invoice.created``: correlate invoice_id onto the Allocation.

    Expects ``event["payload"]`` to contain ``invoice_id`` and
    ``allocation_id``, and ``event["tenant_id"]`` at the top level of the
    envelope. If the allocation can't be found (e.g. already deleted, or a
    stray event), log and return rather than crash — this is a best-effort
    correlation step, not the terminal outcome of the saga.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    allocation_id = payload["allocation_id"]
    invoice_id = payload["invoice_id"]

    try:
        allocation = Allocation.all_objects.get(tenant_id=tenant_id, id=allocation_id)
    except Allocation.DoesNotExist:
        logger.warning(
            "finance.invoice.created for unknown allocation_id=%s tenant_id=%s",
            allocation_id,
            tenant_id,
        )
        return

    allocation.invoice_id = invoice_id
    allocation.save(update_fields=["invoice_id"])


@idempotent
def handle_payment_success(event: dict) -> None:
    """Handle ``finance.payment.success``: confirm the Allocation.

    Finds the pending Allocation by ``invoice_id`` (payload has no
    ``allocation_id`` — see ``handle_invoice_created``) and confirms it,
    emitting ``hostel.allocation.confirmed`` in the same atomic block. If no
    matching pending Allocation is found (already confirmed/released, or the
    correlation step hasn't landed yet), this is a no-op — idempotent safety,
    not an error.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    invoice_id = payload["invoice_id"]

    with transaction.atomic():
        allocation = (
            Allocation.all_objects.select_for_update()
            .filter(tenant_id=tenant_id, invoice_id=invoice_id, status=Allocation.Status.PENDING)
            .first()
        )
        if allocation is None:
            return

        allocation.status = Allocation.Status.CONFIRMED
        allocation.save(update_fields=["status"])

        publish_event(
            "hostel.allocation.confirmed",
            tenant_id=tenant_id,
            payload={
                "allocation_id": str(allocation.id),
                "student_id": str(allocation.student_id),
                "room_id": str(allocation.room_id),
            },
        )


@idempotent
def handle_payment_failed(event: dict) -> None:
    """Handle ``finance.payment.failed``: release the Allocation (compensating action).

    Finds the pending Allocation by ``invoice_id`` and releases it, freeing
    the room seat, in one atomic block. No-op if no matching pending
    Allocation is found.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    invoice_id = payload["invoice_id"]

    with transaction.atomic():
        allocation = (
            Allocation.all_objects.select_for_update()
            .filter(tenant_id=tenant_id, invoice_id=invoice_id, status=Allocation.Status.PENDING)
            .first()
        )
        if allocation is None:
            return

        _release_allocation(allocation)

        publish_event(
            "hostel.allocation.released",
            tenant_id=tenant_id,
            payload={
                "allocation_id": str(allocation.id),
                "student_id": str(allocation.student_id),
                "room_id": str(allocation.room_id),
            },
        )


def dispatch(event: dict) -> None:
    """Route an event to its handler by ``event["type"]``.

    ``suerp_common.events.make_consumer`` takes a single handler; this thin
    dispatcher lets one consumer process (one queue) bind to all three
    routing keys this service needs and fan out to the right handler.
    """
    handlers = {
        "finance.invoice.created": handle_invoice_created,
        "finance.payment.success": handle_payment_success,
        "finance.payment.failed": handle_payment_failed,
    }
    handler = handlers.get(event["type"])
    if handler is None:
        logger.warning("No handler registered for event type=%s", event["type"])
        return
    handler(event)
