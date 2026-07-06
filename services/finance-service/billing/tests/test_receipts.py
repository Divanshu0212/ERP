"""billing.receipts.generate_receipt: renders a PDF receipt (reportlab) with
an embedded QR code (qrcode) linking to a verify page, and an HMAC-signed
verification_token (separate RECEIPT_HMAC_SECRET, not JWT_SIGNING_KEY) that
POST /api/v1/finance/receipts/verify checks against tamper.

Also covers PayView's synchronous hook: a successful /pay call creates a
Receipt in the same request, and its PDF/verify endpoints work end to end.
"""

import uuid
from decimal import Decimal

import jwt
import pytest
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

from billing.models import Invoice, Payment, Receipt  # noqa: E402
from billing.receipts import generate_receipt, verify_token  # noqa: E402


def _make_token(tenant_id, role="student", user_id=None):
    claims = {"sub": str(user_id or uuid.uuid4()), "role": role, "tenant": str(tenant_id)}
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")


def _auth_client(tenant_id, **kwargs):
    client = APIClient()
    token = _make_token(tenant_id, **kwargs)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _make_paid_invoice_and_payment(tenant_id, student_id):
    invoice = Invoice.all_objects.create(
        tenant_id=tenant_id,
        student_id=student_id,
        amount=Decimal("5000.00"),
        purpose="hostel",
        status=Invoice.Status.PAID,
        university_name="Test University",
    )
    payment = Payment.all_objects.create(
        tenant_id=tenant_id,
        invoice=invoice,
        amount=Decimal("5000.00"),
        status=Payment.Status.SUCCESS,
        gateway_ref="sim-123",
    )
    return invoice, payment


def test_generate_receipt_produces_pdf_bytes_and_verifiable_token():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice, payment = _make_paid_invoice_and_payment(tenant_id, student_id)

    receipt = generate_receipt(payment)

    assert receipt.pdf_data.startswith(b"%PDF")
    assert receipt.verification_token
    assert receipt.verify_url.endswith(f"/verify-receipt?token={receipt.verification_token}")
    assert verify_token(receipt.verification_token) == receipt.id


def test_verify_token_rejects_tampered_token():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice, payment = _make_paid_invoice_and_payment(tenant_id, student_id)
    receipt = generate_receipt(payment)

    tampered = receipt.verification_token[:-1] + (
        "a" if receipt.verification_token[-1] != "a" else "b"
    )

    assert verify_token(tampered) is None


def test_pay_creates_receipt_synchronously():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = Invoice.all_objects.create(
        tenant_id=tenant_id,
        student_id=student_id,
        amount=Decimal("100.00"),
        purpose="hostel",
        status=Invoice.Status.PENDING,
        university_name="Test University",
    )
    client = _auth_client(tenant_id, role="student", user_id=student_id)

    response = client.post(
        "/api/v1/finance/pay",
        {"invoice_id": str(invoice.id), "idempotency_key": "idem-1"},
        format="json",
    )

    assert response.status_code == 200, response.content
    payment_id = response.json()["data"]["payment_id"]
    receipt = Receipt.all_objects.get(payment_id=payment_id)
    assert receipt.pdf_data.startswith(b"%PDF")


def test_download_receipt_pdf():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice, payment = _make_paid_invoice_and_payment(tenant_id, student_id)
    receipt = generate_receipt(payment)

    client = _auth_client(tenant_id, role="student", user_id=student_id)
    response = client.get(f"/api/v1/finance/receipts/{receipt.id}/pdf")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_verify_endpoint_valid_token():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice, payment = _make_paid_invoice_and_payment(tenant_id, student_id)
    receipt = generate_receipt(payment)

    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.post(
        "/api/v1/finance/receipts/verify", {"token": receipt.verification_token}, format="json"
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["valid"] is True
    assert body["receipt_no"] == receipt.receipt_no
    assert body["amount"] == "5000.00"


def test_verify_endpoint_invalid_token():
    tenant_id = uuid.uuid4()
    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.post(
        "/api/v1/finance/receipts/verify", {"token": "not-a-real-token"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["data"]["valid"] is False


def test_verify_endpoint_cross_tenant_token_reads_as_invalid_not_500():
    other_tenant_id = uuid.uuid4()
    other_student_id = uuid.uuid4()
    invoice, payment = _make_paid_invoice_and_payment(other_tenant_id, other_student_id)
    receipt = generate_receipt(payment)

    warden_tenant_id = uuid.uuid4()
    warden_client = _auth_client(warden_tenant_id, role="warden")
    response = warden_client.post(
        "/api/v1/finance/receipts/verify", {"token": receipt.verification_token}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["data"]["valid"] is False


def test_student_role_forbidden_from_verify():
    tenant_id = uuid.uuid4()
    student_client = _auth_client(tenant_id, role="student")
    response = student_client.post(
        "/api/v1/finance/receipts/verify", {"token": "whatever"}, format="json"
    )

    assert response.status_code == 403
