"""Tests for Task 4.5: consume ``hostel.allocation.requested`` -> create invoice.

This is the saga step (and the reference EVENT CONSUMER pattern every later
service copies): finance-service reacts to an allocation request from
hostel-service by creating a pending hostel-fee Invoice and emitting
``finance.invoice.created`` — both in one transactional-outbox atomic block.

The handler is called directly with a constructed event dict; no real broker
is needed (``make_consumer`` itself is a thin pika wrapper, exercised
separately/manually, not unit tested here).

Tenant note: consumers run outside request context, so there is no
TenantMiddleware-set tenant in ``suerp_common.tenancy``. The handler resolves
tenant explicitly from the event envelope and uses ``Invoice.all_objects``
(never the tenant-scoped ``objects`` manager) to create rows — see
billing/consumers.py for the full rationale. Tests mirror that: assertions
use ``Invoice.all_objects``/``OutboxEvent.objects`` directly rather than
relying on any ambient tenant context.
"""

import uuid
from decimal import Decimal

import pytest
from billing.consumers import handle_allocation_requested
from billing.models import Invoice
from suerp_common.events import build_event
from suerp_common.outbox import OutboxEvent

pytestmark = pytest.mark.django_db


def _allocation_requested_event(
    tenant_id, student_user_code=None, allocation_id=None, room_id=None
):
    payload = {
        "allocation_id": str(allocation_id or uuid.uuid4()),
        "student_user_code": student_user_code or "STU-100",
        "room_id": str(room_id or uuid.uuid4()),
    }
    return build_event("hostel.allocation.requested", tenant_id=str(tenant_id), payload=payload)


def test_handling_allocation_requested_creates_pending_hostel_invoice_and_emits_event():
    tenant_id = uuid.uuid4()
    student_user_code = "STU-100"
    allocation_id = uuid.uuid4()
    event = _allocation_requested_event(
        tenant_id, student_user_code=student_user_code, allocation_id=allocation_id
    )

    handle_allocation_requested(event)

    invoices = Invoice.all_objects.filter(tenant_id=tenant_id, student_user_code=student_user_code)
    assert invoices.count() == 1
    invoice = invoices.first()
    assert invoice.amount == Decimal("5000.00")
    assert invoice.purpose == "hostel"
    assert invoice.status == Invoice.Status.PENDING

    events = OutboxEvent.objects.filter(type="finance.invoice.created")
    assert events.count() == 1
    emitted = events.first()
    assert str(emitted.tenant_id) == str(tenant_id)
    assert emitted.payload["invoice_id"] == str(invoice.id)
    assert emitted.payload["student_user_code"] == student_user_code
    assert emitted.payload["allocation_id"] == str(allocation_id)
    assert emitted.payload["amount"] == "5000.00"
    assert emitted.payload["purpose"] == "hostel"


def test_handling_same_event_twice_is_idempotent():
    tenant_id = uuid.uuid4()
    student_user_code = "STU-100"
    event = _allocation_requested_event(tenant_id, student_user_code=student_user_code)

    handle_allocation_requested(event)
    handle_allocation_requested(event)  # duplicate delivery, same event_id

    invoices = Invoice.all_objects.filter(tenant_id=tenant_id, student_user_code=student_user_code)
    assert invoices.count() == 1

    events = OutboxEvent.objects.filter(type="finance.invoice.created")
    assert events.count() == 1
