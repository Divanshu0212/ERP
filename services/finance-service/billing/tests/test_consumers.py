"""billing.consumers.handle_allocation_requested: creates a pending hostel
Invoice reacting to hostel.allocation.requested. Covers both the legacy path
(no fee_structure_id — falls back to the hardcoded default) and the new
FeeStructure-driven path introduced alongside room-request approval.
"""

import uuid
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db

from billing.consumers import handle_allocation_requested  # noqa: E402
from billing.models import FeeStructure, Invoice  # noqa: E402


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
