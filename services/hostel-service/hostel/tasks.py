"""Celery tasks for hostel.

``drain_outbox_task`` is wired to Celery Beat (see ``config.settings.
CELERY_BEAT_SCHEDULE``) to periodically relay unpublished ``OutboxEvent`` rows
to RabbitMQ. Mirrors billing/tasks.py in finance-service: one thin task
delegating to ``suerp_common.outbox.drain_outbox``.

``release_stale_pending_allocations`` is the saga's EXPIRY compensating
action: an Allocation created with a fee (Task 4.8/hostel/services.py:
create_allocation) is ``pending`` with a mandatory ``due_date`` until
finance-service settles the invoice (see ``hostel.consumers``). If the
student never pays by that date, this task releases the allocation and
frees the room seat, same as ``handle_payment_failed`` would. It runs
outside any request, so it uses ``Allocation.all_objects``/
``Room.all_objects`` (no ambient tenant) and handles each allocation in its
own transaction so one bad row (e.g. its room was deleted) can't block the
rest of the batch.

A no-fee (direct) allocation is confirmed synchronously at creation and
never reaches this queryset — nothing to expire.
"""

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone
from hostel.models import Allocation, PaymentOutcome, Room
from suerp_common.outbox import drain_outbox

logger = logging.getLogger(__name__)


@shared_task(name="hostel.drain_outbox_task")
def drain_outbox_task() -> int:
    return drain_outbox()


@shared_task(name="hostel.release_stale_pending_allocations")
def release_stale_pending_allocations() -> int:
    """Release Allocations whose payment due_date has passed unpaid.

    Returns the number of allocations released. Each allocation is released
    in its own transaction so a failure on one row doesn't prevent the rest
    of the batch from being processed.
    """
    today = timezone.now().date()
    # Only invoiced allocations past their due_date are candidates. An
    # allocation with no invoice_id hasn't reached the payment stage of the
    # saga yet (or is a no-fee allocation, which has no due_date at all and
    # is already confirmed, never pending). This filter ALSO closes the
    # saga-timeout hole: in the out-of-order window a
    # finance.payment.success can be recorded as PaymentOutcome(applied=
    # False) BEFORE finance.invoice.created stamps the allocation, so a
    # PAID allocation still has invoice_id IS NULL. Excluding null-invoice
    # allocations here means such a paid-but-uncorrelated allocation is
    # never released regardless of event ordering — once invoice.created
    # lands it reconciles to CONFIRMED and is no longer pending.
    stale_ids = list(
        Allocation.all_objects.filter(
            status=Allocation.Status.PENDING,
            due_date__lt=today,
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
                    continue  # not invoiced yet — not an expiry candidate
                # Never release an invoiced allocation that has a recorded
                # payment outcome (in particular a success): its terminal event
                # arrived and is either applied or awaiting correlation.
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
