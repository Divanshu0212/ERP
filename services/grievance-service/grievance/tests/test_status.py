"""Warden-driven grievance status transitions.

Tokens come from ``test_create._auth_client`` — this service's existing
helper — so these tests authenticate exactly the way the rest of the suite
does. Setup rows use ``all_objects`` since no tenant is active outside a
request.
"""

import uuid

import pytest
from grievance.models import Ticket

pytestmark = pytest.mark.django_db

from grievance.tests.test_create import _auth_client  # noqa: E402

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _client(tenant_id, role="warden", sub="WRD-001"):
    return _auth_client(tenant_id, role=role, user_id=sub)


def _ticket(tenant_id, status="open"):
    return Ticket.all_objects.create(
        tenant_id=tenant_id,
        category="hostel",
        description="Broken fan in room 12",
        raised_by="STU-001",
        status=status,
    )


def test_warden_resolves_an_open_ticket():
    ticket = _ticket(TENANT_A)
    client = _client(TENANT_A)

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "resolved"}, format="json"
    )

    assert response.status_code == 200, response.content
    ticket.refresh_from_db()
    assert ticket.status == "resolved"


def test_escalated_tickets_can_be_resolved():
    ticket = _ticket(TENANT_A, status="escalated")
    client = _client(TENANT_A)

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "resolved"}, format="json"
    )

    assert response.status_code == 200, response.content


def test_reopening_a_resolved_ticket_is_rejected():
    ticket = _ticket(TENANT_A, status="resolved")
    client = _client(TENANT_A)

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "open"}, format="json"
    )

    assert response.status_code == 400


def test_an_open_ticket_can_move_to_in_progress():
    ticket = _ticket(TENANT_A)
    client = _client(TENANT_A)

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "in_progress"}, format="json"
    )

    assert response.status_code == 200, response.content


def test_an_unknown_status_is_rejected():
    ticket = _ticket(TENANT_A)
    client = _client(TENANT_A)

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "banana"}, format="json"
    )

    assert response.status_code == 400


def test_students_cannot_change_status():
    ticket = _ticket(TENANT_A)
    client = _client(TENANT_A, role="student", sub="STU-001")

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "resolved"}, format="json"
    )

    assert response.status_code == 403


def test_a_warden_cannot_touch_another_tenants_ticket():
    ticket = _ticket(TENANT_A)
    client = _client(TENANT_B, sub="WRD-002")

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "resolved"}, format="json"
    )

    assert response.status_code == 404
