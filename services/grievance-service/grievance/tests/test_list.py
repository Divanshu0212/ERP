"""Tests for Task 6.5 reads: GET /api/v1/grievance (list) and /{id} (retrieve).

A plain student sees only their OWN tickets; a warden/admin role sees ALL
tickets in their tenant. Tenant isolation holds either way (no cross-tenant
leak). Retrieve is owner- or role-scoped.
"""

import uuid

import jwt
import pytest
from django.conf import settings
from grievance.models import Ticket
from rest_framework.test import APIClient

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


def _make_ticket(tenant_id, raised_by, category="hostel"):
    return Ticket.all_objects.create(
        tenant_id=tenant_id,
        raised_by=raised_by,
        category=category,
        description="something",
    )


def test_student_sees_only_their_own_tickets():
    tenant_id = uuid.uuid4()
    student_a = _student_code()
    student_b = _student_code()
    mine = _make_ticket(tenant_id, student_a)
    _make_ticket(tenant_id, student_b)

    client = _auth_client(tenant_id, user_id=student_a, role="student")
    response = client.get("/api/v1/grievance")

    assert response.status_code == 200
    results = response.json()["data"]["results"]
    ids = {r["id"] for r in results}
    assert ids == {str(mine.id)}


def test_warden_sees_all_tickets_in_tenant():
    tenant_id = uuid.uuid4()
    student_a = _student_code()
    student_b = _student_code()
    t1 = _make_ticket(tenant_id, student_a)
    t2 = _make_ticket(tenant_id, student_b)

    client = _auth_client(tenant_id, role="warden")
    response = client.get("/api/v1/grievance")

    assert response.status_code == 200
    results = response.json()["data"]["results"]
    ids = {r["id"] for r in results}
    assert ids == {str(t1.id), str(t2.id)}


def test_list_is_tenant_isolated():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    _make_ticket(tenant_b, _student_code())

    # Warden in tenant A sees nothing from tenant B.
    client = _auth_client(tenant_a, role="warden")
    response = client.get("/api/v1/grievance")

    assert response.status_code == 200
    assert response.json()["data"]["results"] == []


def test_retrieve_own_ticket():
    tenant_id = uuid.uuid4()
    student = _student_code()
    ticket = _make_ticket(tenant_id, student)

    client = _auth_client(tenant_id, user_id=student, role="student")
    response = client.get(f"/api/v1/grievance/{ticket.id}")

    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(ticket.id)


def test_retrieve_other_users_ticket_is_forbidden_for_student():
    tenant_id = uuid.uuid4()
    owner = _student_code()
    other = _student_code()
    ticket = _make_ticket(tenant_id, owner)

    client = _auth_client(tenant_id, user_id=other, role="student")
    response = client.get(f"/api/v1/grievance/{ticket.id}")

    assert response.status_code in (403, 404)


def test_warden_can_retrieve_any_ticket_in_tenant():
    tenant_id = uuid.uuid4()
    owner = _student_code()
    ticket = _make_ticket(tenant_id, owner)

    client = _auth_client(tenant_id, role="warden")
    response = client.get(f"/api/v1/grievance/{ticket.id}")

    assert response.status_code == 200
    assert response.json()["data"]["id"] == str(ticket.id)
