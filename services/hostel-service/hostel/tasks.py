"""Celery tasks for hostel.

``drain_outbox_task`` is wired to Celery Beat (see ``config.settings.
CELERY_BEAT_SCHEDULE``) to periodically relay unpublished ``OutboxEvent`` rows
to RabbitMQ. Mirrors billing/tasks.py in finance-service: one thin task
delegating to ``suerp_common.outbox.drain_outbox``.

``release_stale_pending_allocations`` (Task 4.9) is the saga's TIMEOUT
compensating action: an Allocation is created ``pending`` (Task 4.8) and
should transition to ``confirmed``/``released`` once finance-service settles
the invoice (Task 4.9's event consumers, see ``hostel.consumers``). If that
never happens — the payment consumer crashes forever, the student never pays
and finance never emits a terminal event, whatever — the allocation would sit
``pending`` forever, holding a room seat hostage. This task finds allocations
that have been ``pending`` longer than ``PENDING_TIMEOUT`` and releases them,
same as ``handle_payment_failed`` would. It also runs outside any request, so
it uses ``Allocation.all_objects``/``Room.all_objects`` (no ambient tenant)
and handles each allocation in its own transaction so one bad row (e.g. its
room was deleted) can't block the rest of the batch.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from hostel.models import Allocation, PaymentOutcome, Room
from suerp_common.outbox import drain_outbox

logger = logging.getLogger(__name__)

PENDING_TIMEOUT = timedelta(minutes=30)


@shared_task(name="hostel.drain_outbox_task")
def drain_outbox_task() -> int:
    return drain_outbox()


@shared_task(name="hostel.release_stale_pending_allocations")
def release_stale_pending_allocations() -> int:
    """Release Allocations that have been pending longer than PENDING_TIMEOUT.

    Returns the number of allocations released. Each allocation is released
    in its own transaction so a failure on one row doesn't prevent the rest
    of the batch from being processed.
    """
    cutoff = timezone.now() - PENDING_TIMEOUT
    # Only invoiced allocations are candidates for the timeout compensation. An
    # allocation with no ``invoice_id`` hasn't even reached the payment stage of
    # the saga, so timing it out on the 30-min PENDING clock is premature. This
    # ``invoice_id__isnull=False`` filter is ALSO what closes the saga-timeout
    # hole: in the out-of-order window a ``finance.payment.success`` can be
    # recorded as ``PaymentOutcome(applied=False)`` BEFORE
    # ``finance.invoice.created`` stamps the allocation, so a PAID allocation
    # still has ``invoice_id IS NULL``. Excluding null-invoice allocations here
    # means such a paid-but-uncorrelated allocation is never released regardless
    # of event ordering — once invoice.created lands it reconciles to CONFIRMED
    # and is no longer pending.
    stale_ids = list(
        Allocation.all_objects.filter(
            status=Allocation.Status.PENDING,
            allocated_on__lt=cutoff,
            invoice_id__isnull=False,
        ).values_list("id", flat=True)
    )

    released = 0
    for allocation_id in stale_ids:
        try:
            with transaction.atomic():
                allocation = Allocation.all_objects.select_for_update().get(id=allocation_id)
                if allocation.status != Allocation.Status.PENDING:
                    continue  # already handled (e.g. by a payment event) — skip
                if allocation.invoice_id is None:
                    continue  # not invoiced yet — not a timeout candidate
                # Never release an invoiced allocation that has a recorded
                # payment outcome (in particular a success): its terminal event
                # arrived and is either applied or awaiting correlation. The
                # null-invoice filter above already handles the pre-correlation
                # window; this guards the correlated-but-not-yet-final case.
                if PaymentOutcome.all_objects.filter(
                    tenant_id=allocation.tenant_id,
                    invoice_id=allocation.invoice_id,
                ).exists():
                    continue
                room = Room.all_objects.select_for_update().get(pk=allocation.room_id)
                allocation.status = Allocation.Status.RELEASED
                allocation.save(update_fields=["status"])
                room.occupied_count = max(0, room.occupied_count - 1)
                room.save(update_fields=["occupied_count"])
                released += 1
        except Exception:
            logger.exception("Failed to release stale allocation id=%s", allocation_id)
    return released
