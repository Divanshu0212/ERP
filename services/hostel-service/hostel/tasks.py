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
from hostel.models import Allocation, Room
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
    stale_ids = list(
        Allocation.all_objects.filter(
            status=Allocation.Status.PENDING, allocated_on__lt=cutoff
        ).values_list("id", flat=True)
    )

    released = 0
    for allocation_id in stale_ids:
        try:
            with transaction.atomic():
                allocation = Allocation.all_objects.select_for_update().get(id=allocation_id)
                if allocation.status != Allocation.Status.PENDING:
                    continue  # already handled (e.g. by a payment event) — skip
                room = Room.all_objects.select_for_update().get(pk=allocation.room_id)
                allocation.status = Allocation.Status.RELEASED
                allocation.save(update_fields=["status"])
                room.occupied_count = max(0, room.occupied_count - 1)
                room.save(update_fields=["occupied_count"])
                released += 1
        except Exception:
            logger.exception("Failed to release stale allocation id=%s", allocation_id)
    return released
