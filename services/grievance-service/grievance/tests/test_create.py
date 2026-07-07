"""Tests for Task 6.5: POST /api/v1/grievance (create ticket + emit event).

A student POSTs a grievance; ``raised_by`` is derived from the JWT ``sub``
claim, one Ticket(open) is created, and — in the SAME transaction (transactional
outbox) — exactly one ``grievance.created`` OutboxEvent is written carrying
``{ticket_id, raised_by, text}`` so ai-service can score it and echo the
recipient back to notification-service.

Tokens are minted directly with pyjwt — grievance-service only ever *verifies*
JWTs (suerp_common.auth.JWTAuthentication), so a token signed with the same
HS256 JWT_SIGNING_KEY carrying sub/role/tenant is indistinguishable from one
auth-service would issue.
"""

import uuid

import jwt
import pytest
from django.conf import settings
from grievance.models import Ticket
from rest_framework.test import APIClient
from suerp_common.outbox import OutboxEvent

pytestmark = pytest.mark.django_db


def _student_code():
    return f"STU{uuid.uuid4().hex[:27]}"


def _make_token(tenant_id, user_id=None, role="student"):
    claims = {
        "sub": user_id or _student_code(),
        "role": role,
        "tenant": str(tenant_id),
    }
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")


def _auth_client(tenant_id, **kwargs):
    client = APIClient()
    token = _make_token(tenant_id, **kwargs)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_create_grievance_returns_201_and_creates_open_ticket():
    tenant_id = uuid.uuid4()
    student_id = _student_code()
    client = _auth_client(tenant_id, user_id=student_id)

    response = client.post(
        "/api/v1/grievance",
        {"category": "hostel", "description": "The mess food is terrible."},
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "open"
    assert body["data"]["category"] == "hostel"
    assert body["data"]["raised_by"] == student_id

    tickets = Ticket.all_objects.filter(tenant_id=tenant_id)
    assert tickets.count() == 1
    ticket = tickets.first()
    assert ticket.raised_by == student_id
    assert ticket.status == "open"


def test_create_grievance_emits_single_grievance_created_event():
    tenant_id = uuid.uuid4()
    student_id = _student_code()
    client = _auth_client(tenant_id, user_id=student_id)

    response = client.post(
        "/api/v1/grievance",
        {"category": "academic", "description": "Grades not uploaded."},
        format="json",
    )
    assert response.status_code == 201
    ticket = Ticket.all_objects.get(tenant_id=tenant_id)

    events = OutboxEvent.objects.filter(type="grievance.created")
    assert events.count() == 1
    event = events.first()
    assert str(event.tenant_id) == str(tenant_id)
    assert event.payload == {
        "ticket_id": str(ticket.id),
        "raised_by": student_id,
        "text": "Grades not uploaded.",
    }


def test_create_grievance_is_tenant_scoped():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    client_a = _auth_client(tenant_a)

    client_a.post(
        "/api/v1/grievance",
        {"category": "it", "description": "Wifi is down."},
        format="json",
    )

    assert Ticket.all_objects.filter(tenant_id=tenant_a).count() == 1
    assert Ticket.all_objects.filter(tenant_id=tenant_b).count() == 0
