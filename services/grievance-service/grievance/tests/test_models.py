"""Model tests for Task 6.5: Ticket, TicketComment.

Both are suerp_common.tenancy.TenantModel subclasses — this proves tenant
isolation (objects vs all_objects) works, plus that a new Ticket defaults to
status "open".
"""

import uuid

import pytest
from grievance.models import Ticket
from suerp_common.tenancy import set_current_tenant

pytestmark = pytest.mark.django_db


def _make_ticket(tenant_id, raised_by=None, category="hostel", description="Leaky tap"):
    return Ticket.all_objects.create(
        tenant_id=tenant_id,
        raised_by=raised_by or uuid.uuid4(),
        category=category,
        description=description,
    )


def test_ticket_default_status_is_open():
    tenant_id = uuid.uuid4()
    ticket = _make_ticket(tenant_id)
    assert ticket.status == "open"
    assert ticket.sentiment_score is None
    assert ticket.urgency is None
    assert ticket.assigned_to is None


def test_ticket_tenant_scoping_isolates_by_tenant():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    ticket_a = _make_ticket(tenant_a)
    ticket_b = _make_ticket(tenant_b)

    try:
        set_current_tenant(str(tenant_a))
        scoped = list(Ticket.objects.all())
        assert scoped == [ticket_a]

        unscoped = set(Ticket.all_objects.all())
        assert unscoped == {ticket_a, ticket_b}
    finally:
        set_current_tenant(None)


def test_ticket_comment_relation():
    tenant_id = uuid.uuid4()
    ticket = _make_ticket(tenant_id)
    comment = ticket.comments.create(
        tenant_id=tenant_id,
        comment_by=uuid.uuid4(),
        text="Looking into it.",
    )
    assert list(ticket.comments.all()) == [comment]
