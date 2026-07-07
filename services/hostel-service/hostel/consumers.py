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
from hostel.models import Allocation, PaymentOutcome, Room
from suerp_common.inbox import idempotent
from suerp_common.outbox import publish_event

logger = logging.getLogger(__name__)


def _apply_outcome(allocation: Allocation, outcome: str, tenant_id) -> None:
    """Apply a payment ``outcome`` to a pending ``allocation``.

    SUCCESS -> confirm the allocation and emit ``hostel.allocation.confirmed``.
    FAILED  -> release the allocation, free the room seat (under a row lock),
    and emit ``hostel.allocation.released``.

    Shared by both correlation paths (payment event lands first vs.
    invoice.created lands first) so the confirm/release + publish logic lives
    in exactly one place. The caller MUST already hold a ``transaction.atomic()``
    and a row lock on ``allocation``; both state change and ``publish_event``
    stay inside that block (transactional outbox guarantee).
    """
    if outcome == PaymentOutcome.Outcome.SUCCESS:
        allocation.status = Allocation.Status.CONFIRMED
        allocation.save(update_fields=["status"])
        publish_event(
            "hostel.allocation.confirmed",
            tenant_id=tenant_id,
            payload={
                "allocation_id": str(allocation.id),
                "student_user_code": allocation.student_user_code,
                "room_id": str(allocation.room_id),
            },
        )
    else:  # PaymentOutcome.Outcome.FAILED — compensating action.
        room = Room.all_objects.select_for_update().get(pk=allocation.room_id)
        allocation.status = Allocation.Status.RELEASED
        allocation.save(update_fields=["status"])
        room.occupied_count = max(0, room.occupied_count - 1)
        room.save(update_fields=["occupied_count"])
        publish_event(
            "hostel.allocation.released",
            tenant_id=tenant_id,
            payload={
                "allocation_id": str(allocation.id),
                "student_user_code": allocation.student_user_code,
                "room_id": str(allocation.room_id),
            },
        )


def _handle_payment_outcome(event: dict, outcome: str) -> None:
    """Correlate a finance payment event (success/failed) to its Allocation.

    Payment payloads carry only ``invoice_id`` (not ``allocation_id``). Two
    orderings are possible because the payment event and its
    ``finance.invoice.created`` are produced by independent finance code paths:

    - invoice.created already landed -> the pending Allocation has ``invoice_id``
      stamped, so we find it, apply the outcome NOW, and record a
      ``PaymentOutcome(applied=True)`` for idempotent-correlation bookkeeping.
    - invoice.created hasn't landed yet -> no allocation matches, so we record a
      ``PaymentOutcome(applied=False)``; ``handle_invoice_created`` will apply
      it when the correlation event finally lands.

    ``get_or_create`` on ``(tenant_id, invoice_id)`` keeps this idempotent at
    the DB level even against the duplicate/racy deliveries the @idempotent
    decorator can't cover (a genuinely distinct event_id carrying the same
    invoice outcome).
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
        if allocation is not None:
            _apply_outcome(allocation, outcome, tenant_id)
            PaymentOutcome.all_objects.get_or_create(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                defaults={"outcome": outcome, "applied": True},
            )
        else:
            # Correlation event hasn't landed yet (or allocation already
            # settled). Persist the outcome so handle_invoice_created can
            # reconcile it later.
            PaymentOutcome.all_objects.get_or_create(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                defaults={"outcome": outcome, "applied": False},
            )


@idempotent
def handle_invoice_created(event: dict) -> None:
    """Handle ``finance.invoice.created``: correlate invoice_id onto the Allocation.

    Expects ``event["payload"]`` to contain ``invoice_id`` and
    ``allocation_id``, and ``event["tenant_id"]`` at the top level of the
    envelope. If the allocation can't be found (e.g. already deleted, or a
    stray event), log and return rather than crash — this is a best-effort
    correlation step, not the terminal outcome of the saga.

    After stamping ``invoice_id``, this reconciles any payment event that
    arrived FIRST: if a not-yet-``applied`` ``PaymentOutcome`` exists for this
    invoice, apply it now (confirm or release) and mark it applied. State
    change + publish stay in one atomic block.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    allocation_id = payload["allocation_id"]
    invoice_id = payload["invoice_id"]

    with transaction.atomic():
        try:
            allocation = Allocation.all_objects.select_for_update().get(
                tenant_id=tenant_id, id=allocation_id
            )
        except Allocation.DoesNotExist:
            logger.warning(
                "finance.invoice.created for unknown allocation_id=%s tenant_id=%s",
                allocation_id,
                tenant_id,
            )
            return

        allocation.invoice_id = invoice_id
        allocation.save(update_fields=["invoice_id"])

        # Reconcile a payment event that arrived before this correlation step.
        pending_outcome = (
            PaymentOutcome.all_objects.select_for_update()
            .filter(tenant_id=tenant_id, invoice_id=invoice_id, applied=False)
            .first()
        )
        if pending_outcome is not None:
            if allocation.status == Allocation.Status.PENDING:
                _apply_outcome(allocation, pending_outcome.outcome, tenant_id)
            # else: the allocation already left PENDING via some other path, so
            # there's nothing to confirm/release — but we must NOT leave a stale
            # applied=False row behind (it would look like an unreconciled
            # outcome forever). Mark it applied either way.
            pending_outcome.applied = True
            pending_outcome.save(update_fields=["applied"])


@idempotent
def handle_payment_success(event: dict) -> None:
    """Handle ``finance.payment.success``: confirm the Allocation.

    Correlates by ``invoice_id`` (payload has no ``allocation_id`` — see
    ``handle_invoice_created``). If the pending Allocation is found, confirm it
    and emit ``hostel.allocation.confirmed`` now; otherwise persist the outcome
    for ``handle_invoice_created`` to apply once correlation lands. See
    ``_handle_payment_outcome``.
    """
    _handle_payment_outcome(event, PaymentOutcome.Outcome.SUCCESS)


@idempotent
def handle_payment_failed(event: dict) -> None:
    """Handle ``finance.payment.failed``: release the Allocation (compensating action).

    Correlates by ``invoice_id``. If the pending Allocation is found, release
    it (freeing the room seat) and emit ``hostel.allocation.released`` now;
    otherwise persist the outcome for ``handle_invoice_created`` to apply once
    correlation lands. See ``_handle_payment_outcome``.
    """
    _handle_payment_outcome(event, PaymentOutcome.Outcome.FAILED)


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
