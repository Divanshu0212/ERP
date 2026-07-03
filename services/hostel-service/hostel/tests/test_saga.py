"""Tests for Task 4.9: CLOSE the allocation saga.

hostel-service started the saga (Task 4.8, ``AllocateView`` ->
``hostel.allocation.requested``) and reacted to it once already
(finance-service's consumer, Task 4.5, creates a pending hostel-fee Invoice
and emits ``finance.invoice.created``). This module closes the loop:

1. ``handle_invoice_created`` — correlation step. finance.payment.success/
   failed payloads don't carry ``allocation_id``, only ``invoice_id``. So when
   ``finance.invoice.created`` arrives (payload DOES carry both), we stamp the
   Allocation with its ``invoice_id`` so later events can find it again.
2. ``handle_payment_success`` — confirms the Allocation and emits
   ``hostel.allocation.confirmed``.
3. ``handle_payment_failed`` — releases the Allocation (the compensating
   action) and decrements the room's ``occupied_count``.
4. ``release_stale_pending_allocations`` (Celery task, tasks.py) — the
   timeout-based compensating action for allocations that never got a
   terminal payment event at all.

All three handlers are called directly with constructed event dicts (no
broker) per the reference pattern in
services/finance-service/billing/consumers.py: ``@idempotent`` outermost,
tenant resolved from the event envelope, ``all_objects`` (consumers run
outside request/TenantMiddleware), state + publish in one
``transaction.atomic()``.
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from hostel.consumers import handle_invoice_created, handle_payment_failed, handle_payment_success
from hostel.models import Allocation, Block, PaymentOutcome, Room
from hostel.tasks import PENDING_TIMEOUT, release_stale_pending_allocations
from suerp_common.events import build_event
from suerp_common.outbox import OutboxEvent

pytestmark = pytest.mark.django_db


def _make_block(tenant_id):
    return Block.all_objects.create(
        tenant_id=tenant_id,
        name="Block A",
        gender_type="M",
        warden_id=uuid.uuid4(),
    )


def _make_room(tenant_id, capacity=2, occupied_count=1, room_no="101"):
    block = _make_block(tenant_id)
    return Room.all_objects.create(
        tenant_id=tenant_id,
        block=block,
        room_no=room_no,
        capacity=capacity,
        occupied_count=occupied_count,
    )


def _make_allocation(tenant_id, room, student_id=None, status="pending", invoice_id=None):
    return Allocation.all_objects.create(
        tenant_id=tenant_id,
        room=room,
        student_id=student_id or uuid.uuid4(),
        status=status,
        invoice_id=invoice_id,
    )


def _invoice_created_event(tenant_id, invoice_id, student_id, allocation_id, amount="5000.00"):
    return build_event(
        "finance.invoice.created",
        tenant_id=str(tenant_id),
        payload={
            "invoice_id": str(invoice_id),
            "student_id": str(student_id),
            "allocation_id": str(allocation_id),
            "amount": amount,
            "purpose": "hostel",
        },
    )


def _payment_success_event(tenant_id, invoice_id, student_id, amount="5000.00"):
    return build_event(
        "finance.payment.success",
        tenant_id=str(tenant_id),
        payload={
            "invoice_id": str(invoice_id),
            "student_id": str(student_id),
            "purpose": "hostel",
            "amount": amount,
        },
    )


def _payment_failed_event(tenant_id, invoice_id, student_id):
    return build_event(
        "finance.payment.failed",
        tenant_id=str(tenant_id),
        payload={
            "invoice_id": str(invoice_id),
            "student_id": str(student_id),
            "purpose": "hostel",
        },
    )


def test_full_saga_happy_path_confirms_allocation_and_emits_event():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1)
    allocation = _make_allocation(tenant_id, room, student_id=student_id, status="pending")

    # Step 1: correlate — finance.invoice.created stamps invoice_id.
    created_event = _invoice_created_event(
        tenant_id, invoice_id=invoice_id, student_id=student_id, allocation_id=allocation.id
    )
    handle_invoice_created(created_event)

    allocation.refresh_from_db()
    assert allocation.invoice_id == invoice_id

    # Step 2: finance.payment.success confirms the allocation by invoice_id.
    success_event = _payment_success_event(tenant_id, invoice_id=invoice_id, student_id=student_id)
    handle_payment_success(success_event)

    allocation.refresh_from_db()
    assert allocation.status == "confirmed"

    events = OutboxEvent.objects.filter(type="hostel.allocation.confirmed")
    assert events.count() == 1
    emitted = events.first()
    assert str(emitted.tenant_id) == str(tenant_id)
    assert emitted.payload == {
        "allocation_id": str(allocation.id),
        "student_id": str(student_id),
        "room_id": str(room.id),
    }


def test_handle_invoice_created_missing_allocation_does_not_crash():
    tenant_id = uuid.uuid4()
    event = _invoice_created_event(
        tenant_id,
        invoice_id=uuid.uuid4(),
        student_id=uuid.uuid4(),
        allocation_id=uuid.uuid4(),  # no matching Allocation exists
    )

    handle_invoice_created(event)  # must not raise


def test_payment_failed_releases_allocation_and_decrements_room():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1)
    allocation = _make_allocation(
        tenant_id, room, student_id=student_id, status="pending", invoice_id=invoice_id
    )

    event = _payment_failed_event(tenant_id, invoice_id=invoice_id, student_id=student_id)
    handle_payment_failed(event)

    allocation.refresh_from_db()
    room.refresh_from_db()
    assert allocation.status == "released"
    assert room.occupied_count == 0


def test_payment_success_is_idempotent_confirms_once_and_emits_one_event():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1)
    allocation = _make_allocation(
        tenant_id, room, student_id=student_id, status="pending", invoice_id=invoice_id
    )

    event = _payment_success_event(tenant_id, invoice_id=invoice_id, student_id=student_id)
    handle_payment_success(event)
    handle_payment_success(event)  # duplicate delivery, same event_id

    allocation.refresh_from_db()
    assert allocation.status == "confirmed"
    assert OutboxEvent.objects.filter(type="hostel.allocation.confirmed").count() == 1


def test_out_of_order_payment_success_before_invoice_created_reconciles():
    """OUT-OF-ORDER: payment.success lands before invoice.created stamps the
    allocation. The success outcome is persisted (applied=False), the
    allocation stays pending; when invoice.created lands it reconciles —
    allocation confirmed, exactly one hostel.allocation.confirmed emitted, and
    the PaymentOutcome flipped applied=True.
    """
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1)
    allocation = _make_allocation(tenant_id, room, student_id=student_id, status="pending")
    # invoice_id NOT yet stamped (handle_invoice_created hasn't run).

    # Payment success arrives first.
    success_event = _payment_success_event(tenant_id, invoice_id=invoice_id, student_id=student_id)
    handle_payment_success(success_event)

    allocation.refresh_from_db()
    assert allocation.status == "pending"
    assert OutboxEvent.objects.filter(type="hostel.allocation.confirmed").count() == 0
    outcome = PaymentOutcome.all_objects.get(tenant_id=tenant_id, invoice_id=invoice_id)
    assert outcome.outcome == "success"
    assert outcome.applied is False

    # Now the correlation event lands — reconciliation applies the outcome.
    created_event = _invoice_created_event(
        tenant_id, invoice_id=invoice_id, student_id=student_id, allocation_id=allocation.id
    )
    handle_invoice_created(created_event)

    allocation.refresh_from_db()
    assert allocation.invoice_id == invoice_id
    assert allocation.status == "confirmed"
    assert OutboxEvent.objects.filter(type="hostel.allocation.confirmed").count() == 1

    outcome.refresh_from_db()
    assert outcome.applied is True


def test_out_of_order_payment_failed_before_invoice_created_reconciles_release():
    """OUT-OF-ORDER failure: payment.failed lands before invoice.created. When
    invoice.created lands, reconciliation releases the allocation and frees the
    room seat.
    """
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1)
    allocation = _make_allocation(tenant_id, room, student_id=student_id, status="pending")

    failed_event = _payment_failed_event(tenant_id, invoice_id=invoice_id, student_id=student_id)
    handle_payment_failed(failed_event)

    allocation.refresh_from_db()
    room.refresh_from_db()
    assert allocation.status == "pending"
    assert room.occupied_count == 1
    outcome = PaymentOutcome.all_objects.get(tenant_id=tenant_id, invoice_id=invoice_id)
    assert outcome.outcome == "failed"
    assert outcome.applied is False

    created_event = _invoice_created_event(
        tenant_id, invoice_id=invoice_id, student_id=student_id, allocation_id=allocation.id
    )
    handle_invoice_created(created_event)

    allocation.refresh_from_db()
    room.refresh_from_db()
    assert allocation.status == "released"
    assert room.occupied_count == 0
    outcome.refresh_from_db()
    assert outcome.applied is True
    assert OutboxEvent.objects.filter(type="hostel.allocation.released").count() == 1


def test_timeout_guard_does_not_release_paid_allocation():
    """Timeout guard: a stale pending allocation that HAS a success
    PaymentOutcome for its invoice must NOT be released by the timeout task.
    """
    tenant_id = uuid.uuid4()
    invoice_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1)
    allocation = _make_allocation(tenant_id, room, status="pending", invoice_id=invoice_id)
    old_time = timezone.now() - PENDING_TIMEOUT - timedelta(minutes=1)
    Allocation.all_objects.filter(id=allocation.id).update(allocated_on=old_time)

    PaymentOutcome.all_objects.create(
        tenant_id=tenant_id, invoice_id=invoice_id, outcome="success", applied=False
    )

    release_stale_pending_allocations()

    allocation.refresh_from_db()
    room.refresh_from_db()
    assert allocation.status == "pending"  # NOT released — it was paid.
    assert room.occupied_count == 1


def test_release_stale_pending_allocations_releases_timed_out_ones_only():
    tenant_id = uuid.uuid4()

    stale_room = _make_room(tenant_id, capacity=2, occupied_count=1, room_no="201")
    stale_allocation = _make_allocation(tenant_id, stale_room, status="pending")
    old_time = timezone.now() - PENDING_TIMEOUT - timedelta(minutes=1)
    Allocation.all_objects.filter(id=stale_allocation.id).update(allocated_on=old_time)

    fresh_room = _make_room(tenant_id, capacity=2, occupied_count=1, room_no="202")
    fresh_allocation = _make_allocation(tenant_id, fresh_room, status="pending")

    release_stale_pending_allocations()

    stale_allocation.refresh_from_db()
    stale_room.refresh_from_db()
    assert stale_allocation.status == "released"
    assert stale_room.occupied_count == 0

    fresh_allocation.refresh_from_db()
    fresh_room.refresh_from_db()
    assert fresh_allocation.status == "pending"
    assert fresh_room.occupied_count == 1
