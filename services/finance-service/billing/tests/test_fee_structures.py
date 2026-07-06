"""GET/POST /api/v1/finance/fee-structures — admin-managed lookup table,
replacing the hardcoded HOSTEL_FEE_AMOUNT constant billing/consumers.py used
before this feature (see Task 4 for the consumer-side wiring).
"""

import uuid

import jwt
import pytest
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

from billing.models import FeeStructure  # noqa: E402


def _make_token(tenant_id, role="admin"):
    claims = {"sub": str(uuid.uuid4()), "role": role, "tenant": str(tenant_id)}
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")


def _auth_client(tenant_id, role="admin"):
    client = APIClient()
    token = _make_token(tenant_id, role=role)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_admin_creates_fee_structure():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="admin")

    response = client.post(
        "/api/v1/finance/fee-structures",
        {"name": "Hostel Fee 2026", "amount": "5000.00", "purpose": "hostel"},
        format="json",
    )

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["name"] == "Hostel Fee 2026"
    assert body["amount"] == "5000.00"
    assert body["purpose"] == "hostel"

    fee = FeeStructure.all_objects.get(id=body["id"])
    assert fee.tenant_id == tenant_id


def test_duplicate_purpose_rejected():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="admin")
    client.post(
        "/api/v1/finance/fee-structures",
        {"name": "Hostel Fee A", "amount": "5000.00", "purpose": "hostel"},
        format="json",
    )

    response = client.post(
        "/api/v1/finance/fee-structures",
        {"name": "Hostel Fee B", "amount": "6000.00", "purpose": "hostel"},
        format="json",
    )

    assert response.status_code == 400


def test_non_admin_cannot_create():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/finance/fee-structures",
        {"name": "Hostel Fee", "amount": "5000.00", "purpose": "hostel"},
        format="json",
    )

    assert response.status_code == 403


def test_any_authenticated_role_can_list():
    tenant_id = uuid.uuid4()
    admin = _auth_client(tenant_id, role="admin")
    admin.post(
        "/api/v1/finance/fee-structures",
        {"name": "Hostel Fee", "amount": "5000.00", "purpose": "hostel"},
        format="json",
    )

    warden = _auth_client(tenant_id, role="warden")
    response = warden.get("/api/v1/finance/fee-structures")

    assert response.status_code == 200
    items = response.json()["data"]
    results = items["results"] if isinstance(items, dict) and "results" in items else items
    assert len(results) == 1
