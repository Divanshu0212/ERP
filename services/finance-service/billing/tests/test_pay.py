"""Tests for Task 4.4: POST /api/v1/finance/pay.

Covers the transactional-outbox guarantee for payments (Payment + Invoice
status update + finance.payment.success/failed event commit together),
idempotency-key dedup under replay, and tenant isolation (a token for tenant
B cannot pay tenant A's invoice).

Tokens are minted directly with pyjwt (``import jwt``) rather than going
through auth-service's login flow — finance-service only ever *verifies*
JWTs (see suerp_common.auth.JWTAuthentication), so a token signed with the
same HS256 ``JWT_SIGNING_KEY`` and carrying the sub/role/tenant claims is
indistinguishable from one auth-service would have issued.
"""

import uuid

import jwt
import pytest
from billing.models import Invoice, Payment
from django.conf import settings
from rest_framework.test import APIClient
from suerp_common.outbox import OutboxEvent

pytestmark = pytest.mark.django_db


def _make_token(tenant_id, user_id=None, role="student"):
    claims = {
        "sub": str(user_id or uuid.uuid4()),
        "role": role,
        "tenant": str(tenant_id),
    }
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")


@pytest.fixture
def client():
    return APIClient()


def _auth_client(tenant_id, **kwargs):
    client = APIClient()
    token = _make_token(tenant_id, **kwargs)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _make_invoice(tenant_id, amount="100.00", purpose="hostel", student_user_code=None):
    return Invoice.all_objects.create(
        tenant_id=tenant_id,
        student_user_code=student_user_code or "STU-100",
        amount=amount,
        purpose=purpose,
    )


def test_pay_success_marks_invoice_paid_creates_payment_and_emits_event():
    tenant_id = uuid.uuid4()
    invoice = _make_invoice(tenant_id, amount="100.00", purpose="hostel")
    client = _auth_client(tenant_id)

    response = client.post(
        "/api/v1/finance/pay",
        {"invoice_id": str(invoice.id), "idempotency_key": "key-success-1"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "success"

    invoice.refresh_from_db()
    assert invoice.status == "paid"

    payments = Payment.all_objects.filter(invoice=invoice)
    assert payments.count() == 1
    payment = payments.first()
    assert payment.status == "success"

    events = OutboxEvent.objects.filter(type="finance.payment.success")
    assert events.count() == 1
    event = events.first()
    assert str(event.tenant_id) == str(tenant_id)
    assert event.payload["invoice_id"] == str(invoice.id)
    assert event.payload["student_user_code"] == invoice.student_user_code
    assert event.payload["purpose"] == "hostel"
    assert event.payload["amount"] == "100.00"

    # No failure event leaked from this flow.
    assert OutboxEvent.objects.filter(type="finance.payment.failed").count() == 0


def test_pay_failure_marks_invoice_failed_creates_payment_and_emits_event():
    tenant_id = uuid.uuid4()
    invoice = _make_invoice(tenant_id, amount="9.99", purpose="tuition")
    client = _auth_client(tenant_id)

    response = client.post(
        "/api/v1/finance/pay",
        {"invoice_id": str(invoice.id), "idempotency_key": "key-fail-1"},
        format="json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "failed"

    invoice.refresh_from_db()
    assert invoice.status == "failed"

    payments = Payment.all_objects.filter(invoice=invoice)
    assert payments.count() == 1
    assert payments.first().status == "failed"

    events = OutboxEvent.objects.filter(type="finance.payment.failed")
    assert events.count() == 1
    event = events.first()
    assert event.payload["invoice_id"] == str(invoice.id)
    assert event.payload["student_user_code"] == invoice.student_user_code
    assert event.payload["purpose"] == "tuition"

    assert OutboxEvent.objects.filter(type="finance.payment.success").count() == 0


def test_pay_is_idempotent_under_replay_of_same_key():
    tenant_id = uuid.uuid4()
    invoice = _make_invoice(tenant_id, amount="100.00", purpose="hostel")
    client = _auth_client(tenant_id)
    body = {"invoice_id": str(invoice.id), "idempotency_key": "key-replay-1"}

    first = client.post("/api/v1/finance/pay", body, format="json")
    second = client.post("/api/v1/finance/pay", body, format="json")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["status"] == "success"
    assert second.json()["data"]["status"] == "success"

    assert Payment.all_objects.filter(invoice=invoice).count() == 1
    assert OutboxEvent.objects.filter(type="finance.payment.success").count() == 1
    assert OutboxEvent.objects.filter(type="finance.payment.failed").count() == 0

    invoice.refresh_from_db()
    assert invoice.status == "paid"


def test_pay_cannot_reach_invoice_from_a_different_tenant():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    invoice = _make_invoice(tenant_a, amount="100.00", purpose="hostel")
    client_b = _auth_client(tenant_b)

    response = client_b.post(
        "/api/v1/finance/pay",
        {"invoice_id": str(invoice.id), "idempotency_key": "key-cross-tenant"},
        format="json",
    )

    assert response.status_code == 404
    assert response.json()["success"] is False

    invoice.refresh_from_db()
    assert invoice.status == "pending"
    assert Payment.all_objects.filter(invoice=invoice).count() == 0
    assert OutboxEvent.objects.count() == 0


def test_pay_requires_authentication(client):
    tenant_id = uuid.uuid4()
    invoice = _make_invoice(tenant_id)

    response = client.post(
        "/api/v1/finance/pay",
        {"invoice_id": str(invoice.id), "idempotency_key": "key-noauth"},
        format="json",
    )

    assert response.status_code == 401
