"""Tests for Task 6.3 consumer: finance.payment.success -> activate a Pass.

Follows the reference consumer pattern (finance/hostel): the handler is called
directly with a constructed event dict (no broker). ``@idempotent`` makes a
redelivery a no-op; tenant is resolved from the envelope and rows use
``Pass.all_objects`` (consumers run outside request/TenantMiddleware).
"""

import uuid

import pytest
from suerp_common.events import build_event
from transport.consumers import handle_payment_success
from transport.models import Pass

pytestmark = pytest.mark.django_db


def _payment_success_event(tenant_id, student_user_code, purpose="transport", **extra):
    payload = {
        "invoice_id": str(uuid.uuid4()),
        "student_user_code": student_user_code,
        "purpose": purpose,
        "amount": "1500.00",
    }
    payload.update(extra)
    return build_event("finance.payment.success", tenant_id=str(tenant_id), payload=payload)


def test_transport_payment_activates_pass():
    tenant_id = uuid.uuid4()
    student_user_code = "STU-100"
    event = _payment_success_event(tenant_id, student_user_code, purpose="transport")

    handle_payment_success(event)

    passes = Pass.all_objects.filter(tenant_id=tenant_id, student_user_code=student_user_code)
    assert passes.count() == 1
    assert passes.first().active is True


def test_bus_pass_purpose_also_activates_pass():
    tenant_id = uuid.uuid4()
    student_user_code = "STU-100"
    event = _payment_success_event(tenant_id, student_user_code, purpose="bus_pass")

    handle_payment_success(event)

    assert (
        Pass.all_objects.filter(
            tenant_id=tenant_id, student_user_code=student_user_code, active=True
        ).count()
        == 1
    )


def test_redelivery_same_event_id_is_idempotent():
    tenant_id = uuid.uuid4()
    student_user_code = "STU-100"
    event = _payment_success_event(tenant_id, student_user_code, purpose="transport")

    handle_payment_success(event)
    handle_payment_success(event)  # duplicate delivery, same event_id

    passes = Pass.all_objects.filter(
        tenant_id=tenant_id, student_user_code=student_user_code, active=True
    )
    assert passes.count() == 1


def test_hostel_purpose_is_skipped_no_pass_created():
    tenant_id = uuid.uuid4()
    student_user_code = "STU-100"
    event = _payment_success_event(tenant_id, student_user_code, purpose="hostel")

    handle_payment_success(event)

    assert (
        Pass.all_objects.filter(tenant_id=tenant_id, student_user_code=student_user_code).count()
        == 0
    )
