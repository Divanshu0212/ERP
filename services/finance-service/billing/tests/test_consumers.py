"""billing.consumers.handle_allocation_requested: creates a pending hostel
Invoice reacting to hostel.allocation.requested. Covers both the legacy path
(no fee_structure_id — falls back to the hardcoded default) and the new
FeeStructure-driven path introduced alongside room-request approval.
"""

import uuid
from decimal import Decimal

import jwt
import pytest
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

from billing.consumers import handle_allocation_requested  # noqa: E402
from billing.models import FeeStructure, Invoice, Receipt  # noqa: E402


def _auth_client(tenant_id, role="student", user_id=None):
    claims = {"sub": str(user_id or uuid.uuid4()), "role": role, "tenant": str(tenant_id)}
    token = jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _event(tenant_id, **payload_overrides):
    payload = {
        "allocation_id": str(uuid.uuid4()),
        "student_id": str(uuid.uuid4()),
        "room_id": str(uuid.uuid4()),
        "fee_structure_id": None,
        "university_name": "",
    }
    payload.update(payload_overrides)
    return {"event_id": str(uuid.uuid4()), "type": "hostel.allocation.requested",
             "tenant_id": str(tenant_id), "payload": payload}


def test_uses_fee_structure_amount_and_stamps_university_name():
    tenant_id = uuid.uuid4()
    fee = FeeStructure.all_objects.create(
        tenant_id=tenant_id, name="Hostel Fee 2026", amount=Decimal("7500.00"), purpose="hostel"
    )
    event = _event(tenant_id, fee_structure_id=str(fee.id), university_name="Test University")

    handle_allocation_requested(event)

    invoice = Invoice.all_objects.get(tenant_id=tenant_id)
    assert invoice.amount == Decimal("7500.00")
    assert invoice.university_name == "Test University"


def test_falls_back_to_hardcoded_default_without_fee_structure():
    tenant_id = uuid.uuid4()
    event = _event(tenant_id)

    handle_allocation_requested(event)

    invoice = Invoice.all_objects.get(tenant_id=tenant_id)
    assert invoice.amount == Decimal("5000.00")
    assert invoice.university_name == ""


def test_missing_fee_structure_id_falls_back_gracefully():
    tenant_id = uuid.uuid4()
    nonexistent_id = str(uuid.uuid4())
    event = _event(tenant_id, fee_structure_id=nonexistent_id)

    handle_allocation_requested(event)

    invoice = Invoice.all_objects.get(tenant_id=tenant_id)
    assert invoice.amount == Decimal("5000.00")


def _hostel_allocation_requested_event(tenant_id, student_id, fee_structure_id, university_name):
    """Build a ``hostel.allocation.requested`` event with the LITERAL payload
    shape hostel-service's ``create_allocation()`` emits via ``publish_event``
    (services/hostel-service/hostel/services.py): payload keys ``allocation_id``,
    ``student_id``, ``room_id`` (all str-of-UUID), ``fee_structure_id`` (str or
    None), ``university_name`` (str). Uses that exact shape as the input rather
    than a simplified stand-in, so this test spans the finance half of the chain
    against hostel's real boundary contract.
    """
    return {
        "event_id": str(uuid.uuid4()),
        "type": "hostel.allocation.requested",
        "tenant_id": str(tenant_id),
        "payload": {
            "allocation_id": str(uuid.uuid4()),
            "student_id": str(student_id),
            "room_id": str(uuid.uuid4()),
            "fee_structure_id": str(fee_structure_id) if fee_structure_id else None,
            "university_name": university_name,
        },
    }


def test_full_chain_from_hostel_event_payload_shape_to_verified_receipt():
    """End-to-end (finance half): take hostel's real allocation.requested payload
    shape -> handle_allocation_requested creates the invoice -> pay it via the
    real PayView endpoint -> a Receipt is created with the right amount/
    university_name -> verifying its token returns valid: true. This is the
    realistic boundary a single test can span given DB-per-service (no shared
    test DB / live event bus between hostel- and finance-service)."""
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    fee = FeeStructure.all_objects.create(
        tenant_id=tenant_id, name="Hostel Fee 2026", amount=Decimal("7500.00"), purpose="hostel"
    )

    event = _hostel_allocation_requested_event(
        tenant_id, student_id, fee_structure_id=fee.id, university_name="Test University"
    )

    # Step 1: finance consumes hostel's event -> pending invoice.
    handle_allocation_requested(event)
    invoice = Invoice.all_objects.get(tenant_id=tenant_id)
    assert invoice.amount == Decimal("7500.00")
    assert invoice.university_name == "Test University"

    # Step 2: the student pays that invoice through the real PayView endpoint.
    student_client = _auth_client(tenant_id, role="student", user_id=student_id)
    pay_response = student_client.post(
        "/api/v1/finance/pay",
        {"invoice_id": str(invoice.id), "idempotency_key": "chain-idem-1"},
        format="json",
    )
    assert pay_response.status_code == 200, pay_response.content

    # Step 3: a Receipt exists for that payment, with the right amount/university.
    receipt = Receipt.all_objects.get(payment__invoice=invoice)
    assert receipt.pdf_data.startswith(b"%PDF")
    assert invoice.university_name == "Test University"
    assert invoice.amount == Decimal("7500.00")

    # Step 4: verifying the receipt's token reads as valid.
    warden_client = _auth_client(tenant_id, role="warden")
    verify_response = warden_client.post(
        "/api/v1/finance/receipts/verify",
        {"token": receipt.verification_token},
        format="json",
    )
    assert verify_response.status_code == 200, verify_response.content
    body = verify_response.json()["data"]
    assert body["valid"] is True
    assert body["amount"] == "7500.00"
    assert body["university_name"] == "Test University"
