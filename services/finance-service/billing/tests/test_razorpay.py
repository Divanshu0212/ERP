"""Tests for the additive Razorpay path on finance-service.

Covers the razorpay-order endpoint (configured vs not) and PayView's real
verification branch (signature success/failure), plus confirmation that the
simulated-gateway default is untouched when no razorpay fields are sent.

Razorpay's SDK is never called for real — ``suerp_common.razorpay_gateway``'s
``create_order``/``verify_signature``/``is_configured`` are monkeypatched, so
no network calls to Razorpay happen in tests.
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
    claims = {"sub": str(user_id or uuid.uuid4()), "role": role, "tenant": str(tenant_id)}
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")


def _auth_client(tenant_id, **kwargs):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_make_token(tenant_id, **kwargs)}")
    return client


def _make_invoice(tenant_id, amount="100.00", purpose="hostel", student_id=None):
    return Invoice.all_objects.create(
        tenant_id=tenant_id,
        student_id=student_id or uuid.uuid4(),
        amount=amount,
        purpose=purpose,
    )


def test_razorpay_order_returns_400_when_not_configured(monkeypatch):
    from billing import views

    monkeypatch.setattr(views.razorpay_gateway, "is_configured", lambda: False)
    tenant_id = uuid.uuid4()
    invoice = _make_invoice(tenant_id)

    resp = _auth_client(tenant_id).post(f"/api/v1/finance/invoices/{invoice.id}/razorpay-order")
    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_razorpay_order_created_when_configured(monkeypatch):
    from billing import views

    monkeypatch.setattr(views.razorpay_gateway, "is_configured", lambda: True)
    monkeypatch.setattr(
        views.razorpay_gateway,
        "create_order",
        lambda amount, receipt: {
            "order_id": "order_TEST123",
            "amount": str(amount),
            "currency": "INR",
            "key_id": "test_key_id",
        },
    )
    tenant_id = uuid.uuid4()
    invoice = _make_invoice(tenant_id, amount="250.00")

    resp = _auth_client(tenant_id).post(f"/api/v1/finance/invoices/{invoice.id}/razorpay-order")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["order_id"] == "order_TEST123"
    assert data["amount"] == "250.00"
    assert data["currency"] == "INR"


def test_razorpay_order_cross_tenant_is_404(monkeypatch):
    from billing import views

    monkeypatch.setattr(views.razorpay_gateway, "is_configured", lambda: True)
    invoice = _make_invoice(uuid.uuid4())
    resp = _auth_client(uuid.uuid4()).post(f"/api/v1/finance/invoices/{invoice.id}/razorpay-order")
    assert resp.status_code == 404


def test_pay_with_valid_razorpay_signature_marks_paid(monkeypatch):
    from billing import views

    monkeypatch.setattr(views.razorpay_gateway, "verify_signature", lambda *a: True)
    tenant_id = uuid.uuid4()
    invoice = _make_invoice(tenant_id, amount="500.00", purpose="tuition")

    resp = _auth_client(tenant_id).post(
        "/api/v1/finance/pay",
        {
            "invoice_id": str(invoice.id),
            "idempotency_key": "rzp-ok-1",
            "razorpay_order_id": "order_TEST123",
            "razorpay_payment_id": "pay_TEST456",
            "razorpay_signature": "sig_TEST789",
        },
        format="json",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "success"
    assert body["data"]["gateway_ref"] == "pay_TEST456"

    invoice.refresh_from_db()
    assert invoice.status == "paid"
    payment = Payment.all_objects.get(invoice=invoice)
    assert payment.gateway_ref == "pay_TEST456"
    assert OutboxEvent.objects.filter(type="finance.payment.success").count() == 1


def test_pay_with_invalid_razorpay_signature_marks_failed(monkeypatch):
    from billing import views

    monkeypatch.setattr(views.razorpay_gateway, "verify_signature", lambda *a: False)
    tenant_id = uuid.uuid4()
    invoice = _make_invoice(tenant_id, amount="500.00")

    resp = _auth_client(tenant_id).post(
        "/api/v1/finance/pay",
        {
            "invoice_id": str(invoice.id),
            "idempotency_key": "rzp-bad-1",
            "razorpay_order_id": "order_TEST123",
            "razorpay_payment_id": "pay_TEST456",
            "razorpay_signature": "sig_BAD",
        },
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "failed"

    invoice.refresh_from_db()
    assert invoice.status == "failed"
    assert OutboxEvent.objects.filter(type="finance.payment.failed").count() == 1


def test_pay_without_razorpay_fields_uses_simulated_gateway(monkeypatch):
    """No razorpay fields -> the real path must never be consulted."""
    from billing import views

    def _boom(*a, **k):  # pragma: no cover - must not be called
        raise AssertionError("razorpay_gateway must not be used without proof")

    monkeypatch.setattr(views.razorpay_gateway, "verify_signature", _boom)
    tenant_id = uuid.uuid4()
    invoice = _make_invoice(tenant_id, amount="100.00")

    resp = _auth_client(tenant_id).post(
        "/api/v1/finance/pay",
        {"invoice_id": str(invoice.id), "idempotency_key": "sim-1"},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "success"
