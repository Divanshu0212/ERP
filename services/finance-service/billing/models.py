"""Billing domain models: FeeStructure, Invoice, Payment, Receipt.

All four are ``suerp_common.tenancy.TenantModel`` subclasses — finance-service
is a normal resource service (unlike auth-service, which is the identity
authority and has documented reasons to deviate from TenantModel). ``objects``
is transparently scoped to the active tenant; ``all_objects`` bypasses scoping
for system operations.

``Invoice.student_id`` is a bare UUID, not a ForeignKey: student-service owns
the Student table in its own database (DB-per-service), so finance-service can
only ever hold an opaque reference to it, never a real FK.
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class FeeStructure(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    purpose = models.CharField(max_length=100)  # e.g. "hostel", "tuition"
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.purpose})"


class Invoice(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Reference to student-service's Student table. No cross-service FK
    # (DB-per-service) — this is a bare, opaque UUID.
    student_id = models.UUIDField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    purpose = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="invoice_tenant_status"),
            models.Index(fields=["tenant_id", "student_id"], name="invoice_tenant_student"),
        ]

    def __str__(self):
        return f"Invoice {self.id} ({self.status})"


class Payment(TenantModel):
    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices)
    gateway_ref = models.CharField(max_length=255)
    # Dedup key for the /pay endpoint: replaying the same idempotency_key for
    # the same invoice must return the prior outcome instead of re-charging
    # or re-emitting an event (see billing/views.py PayView).
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["invoice", "idempotency_key"], name="payment_invoice_idem"),
        ]

    def __str__(self):
        return f"Payment {self.id} ({self.status})"


class Receipt(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name="receipt")
    receipt_no = models.CharField(max_length=100)
    pdf_url = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.receipt_no
