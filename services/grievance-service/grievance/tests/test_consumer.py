"""Tests for Task 6.6 consumer: grievance.scored -> apply sentiment/urgency.

The handler is called directly with a constructed event dict (no broker).
``@idempotent`` makes a redelivery a no-op; tenant is resolved from the envelope
and rows use ``Ticket.all_objects`` (consumers run outside request/
TenantMiddleware). urgency high/critical auto-escalates the ticket status.
"""

import uuid

import pytest
from grievance.consumers import handle_grievance_scored
from grievance.models import Ticket
from suerp_common.events import build_event

pytestmark = pytest.mark.django_db


def _student_code():
    return f"STU{uuid.uuid4().hex[:27]}"


def _make_ticket(tenant_id, raised_by=None):
    return Ticket.all_objects.create(
        tenant_id=tenant_id,
        raised_by=raised_by or _student_code(),
        category="hostel",
        description="The warden is harassing me.",
    )


def _scored_event(tenant_id, ticket_id, raised_by, sentiment=-0.8, urgency="critical"):
    return build_event(
        "grievance.scored",
        tenant_id=str(tenant_id),
        payload={
            "ticket_id": str(ticket_id),
            "sentiment": sentiment,
            "urgency": urgency,
            "raised_by": str(raised_by),
        },
    )


def test_critical_urgency_escalates_ticket():
    tenant_id = uuid.uuid4()
    ticket = _make_ticket(tenant_id)
    event = _scored_event(
        tenant_id, ticket.id, ticket.raised_by, sentiment=-0.9, urgency="critical"
    )

    handle_grievance_scored(event)

    ticket.refresh_from_db()
    assert ticket.status == "escalated"
    assert ticket.urgency == "critical"
    assert ticket.sentiment_score == pytest.approx(-0.9)


def test_high_urgency_escalates_ticket():
    tenant_id = uuid.uuid4()
    ticket = _make_ticket(tenant_id)
    event = _scored_event(tenant_id, ticket.id, ticket.raised_by, sentiment=-0.5, urgency="high")

    handle_grievance_scored(event)

    ticket.refresh_from_db()
    assert ticket.status == "escalated"
    assert ticket.urgency == "high"


def test_low_urgency_keeps_status_open():
    tenant_id = uuid.uuid4()
    ticket = _make_ticket(tenant_id)
    event = _scored_event(tenant_id, ticket.id, ticket.raised_by, sentiment=0.3, urgency="low")

    handle_grievance_scored(event)

    ticket.refresh_from_db()
    assert ticket.status == "open"
    assert ticket.urgency == "low"
    assert ticket.sentiment_score == pytest.approx(0.3)


def test_redelivery_same_event_id_is_idempotent():
    tenant_id = uuid.uuid4()
    ticket = _make_ticket(tenant_id)
    event = _scored_event(
        tenant_id, ticket.id, ticket.raised_by, sentiment=-0.9, urgency="critical"
    )

    handle_grievance_scored(event)
    handle_grievance_scored(event)  # duplicate delivery, same event_id

    ticket.refresh_from_db()
    assert ticket.status == "escalated"
    assert ticket.urgency == "critical"
    assert ticket.sentiment_score == pytest.approx(-0.9)


def test_scored_event_for_other_tenant_does_not_affect_this_ticket():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    ticket = _make_ticket(tenant_a)
    # Same ticket_id but delivered under tenant B -> must not be found/mutated.
    event = _scored_event(tenant_b, ticket.id, ticket.raised_by, urgency="critical")

    handle_grievance_scored(event)

    ticket.refresh_from_db()
    assert ticket.status == "open"
    assert ticket.urgency is None
    assert ticket.sentiment_score is None
