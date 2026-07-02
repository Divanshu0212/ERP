"""Model tests for Task 4.2: FeeStructure, Invoice, Payment, Receipt.

Invoice/Payment/Receipt/FeeStructure are all suerp_common.tenancy.TenantModel
subclasses — this proves tenant isolation (objects vs all_objects) works on
finance-service's own models, plus default status and the Invoice<->Payment
relation.
"""

import uuid

import pytest
from billing.models import Invoice, Payment
from suerp_common.tenancy import set_current_tenant

pytestmark = pytest.mark.django_db


def test_tenant_scoping_isolates_invoices_by_tenant():
    """Two invoices created under different tenant_ids: with tenant context
    set to A, `Invoice.objects` returns only A's invoice while `all_objects`
    (unscoped) returns both."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    invoice_a = Invoice.all_objects.create(
        tenant_id=tenant_a,
        student_id=uuid.uuid4(),
        amount="100.00",
        purpose="hostel",
    )
    invoice_b = Invoice.all_objects.create(
        tenant_id=tenant_b,
        student_id=uuid.uuid4(),
        amount="200.00",
        purpose="tuition",
    )

    try:
        set_current_tenant(str(tenant_a))
        scoped = list(Invoice.objects.all())
        assert scoped == [invoice_a]

        unscoped = set(Invoice.all_objects.all())
        assert unscoped == {invoice_a, invoice_b}
    finally:
        set_current_tenant(None)


def test_invoice_default_status_is_pending():
    invoice = Invoice.all_objects.create(
        tenant_id=uuid.uuid4(),
        student_id=uuid.uuid4(),
        amount="50.00",
        purpose="hostel",
    )
    assert invoice.status == "pending"


def test_payment_attaches_to_invoice():
    tenant = uuid.uuid4()
    invoice = Invoice.all_objects.create(
        tenant_id=tenant,
        student_id=uuid.uuid4(),
        amount="50.00",
        purpose="hostel",
    )

    Payment.all_objects.create(
        tenant_id=tenant,
        invoice=invoice,
        amount="50.00",
        status="success",
        gateway_ref="ref-123",
    )

    assert invoice.payments.count() == 1
