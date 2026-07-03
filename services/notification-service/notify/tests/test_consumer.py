"""Tests for Task 5.3: event fan-out consumer -> create inbox Notification.

notification-service is the terminal saga consumer: it reacts to
finance.payment.success, hostel.allocation.confirmed, and grievance.scored by
writing a Notification row for the recipient user. Unlike finance/hostel it
does NOT publish any follow-on event, so there is no outbox assertion here.

Handlers are called via the dispatcher (mirroring how the running consumer
routes by ``event["type"]``) with a constructed event dict; no real broker is
needed. Tenant note: consumers run outside request context, so handlers
resolve tenant explicitly from the event envelope and use
``Notification.all_objects`` — see notify/consumers.py for the full rationale.
"""

import uuid

import pytest
from notify.consumers import dispatch_event
from notify.models import Notification
from suerp_common.events import build_event

pytestmark = pytest.mark.django_db


def test_payment_success_creates_one_notification_and_is_idempotent():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    event = build_event(
        "finance.payment.success",
        tenant_id=str(tenant_id),
        payload={
            "invoice_id": str(uuid.uuid4()),
            "student_id": str(student_id),
            "purpose": "hostel",
            "amount": "5000.00",
        },
    )

    dispatch_event(event)

    notes = Notification.all_objects.filter(tenant_id=tenant_id, user_id=student_id)
    assert notes.count() == 1
    note = notes.first()
    assert note.title == "Payment successful"
    assert "hostel" in note.body
    assert "5000.00" in note.body

    # Redelivery of the same event_id creates nothing extra.
    dispatch_event(event)
    assert Notification.all_objects.filter(tenant_id=tenant_id, user_id=student_id).count() == 1


def test_allocation_confirmed_creates_one_notification_and_is_idempotent():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    event = build_event(
        "hostel.allocation.confirmed",
        tenant_id=str(tenant_id),
        payload={
            "allocation_id": str(uuid.uuid4()),
            "student_id": str(student_id),
            "room_id": str(uuid.uuid4()),
        },
    )

    dispatch_event(event)

    notes = Notification.all_objects.filter(tenant_id=tenant_id, user_id=student_id)
    assert notes.count() == 1
    assert notes.first().title == "Hostel room confirmed"

    dispatch_event(event)
    assert Notification.all_objects.filter(tenant_id=tenant_id, user_id=student_id).count() == 1


def test_grievance_scored_with_student_id_creates_notification():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    event = build_event(
        "grievance.scored",
        tenant_id=str(tenant_id),
        payload={
            "ticket_id": str(uuid.uuid4()),
            "student_id": str(student_id),
            "sentiment": "negative",
            "urgency": "high",
        },
    )

    dispatch_event(event)

    notes = Notification.all_objects.filter(tenant_id=tenant_id, user_id=student_id)
    assert notes.count() == 1
    note = notes.first()
    assert note.title == "Grievance update"
    assert "high" in note.body


def test_grievance_scored_with_raised_by_fallback_creates_notification():
    tenant_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    event = build_event(
        "grievance.scored",
        tenant_id=str(tenant_id),
        payload={
            "ticket_id": str(uuid.uuid4()),
            "raised_by": str(owner_id),
            "sentiment": "neutral",
            "urgency": "low",
        },
    )

    dispatch_event(event)

    notes = Notification.all_objects.filter(tenant_id=tenant_id, user_id=owner_id)
    assert notes.count() == 1
    assert "low" in notes.first().body


def test_grievance_scored_without_recipient_is_skipped_gracefully():
    tenant_id = uuid.uuid4()
    event = build_event(
        "grievance.scored",
        tenant_id=str(tenant_id),
        payload={
            "ticket_id": str(uuid.uuid4()),
            "sentiment": "neutral",
            "urgency": "low",
        },
    )

    # No recipient id in the payload -> skipped without raising.
    dispatch_event(event)

    assert Notification.all_objects.filter(tenant_id=tenant_id).count() == 0
