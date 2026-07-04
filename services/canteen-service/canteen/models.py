"""Canteen domain models: MenuItem, Order, OrderItem.

All three are ``suerp_common.tenancy.TenantModel`` subclasses, so ``objects``
is transparently tenant-scoped and ``all_objects`` bypasses scoping.

``Order.student_id`` is a bare UUID, not a ForeignKey: auth-service/
student-service owns that row in its own database (DB-per-service), so
canteen-service can only ever hold an opaque reference to it. Same pattern as
transport-service's ``Booking.student_id``.

``OrderItem.unit_price`` is a SNAPSHOT of ``MenuItem.price`` at order-creation
time, deliberately copied rather than live-joined: a later price edit must not
retroactively change the total of an already-placed order.
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class MenuItem(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Order(TenantModel):
    class Status(models.TextChoices):
        PLACED = "placed", "Placed"
        PREPARING = "preparing", "Preparing"
        READY = "ready", "Ready"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Reference to auth-service's User table (the student). No cross-service FK
    # (DB-per-service) — this is a bare, opaque UUID.
    student_id = models.UUIDField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLACED)
    total = models.DecimalField(max_digits=8, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "created_at"], name="order_tenant_created"),
            models.Index(fields=["tenant_id", "student_id"], name="order_tenant_student"),
        ]

    def __str__(self):
        return f"Order {self.id} ({self.status})"


class OrderItem(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    menu_item = models.ForeignKey(MenuItem, on_delete=models.PROTECT)
    quantity = models.PositiveSmallIntegerField()
    # Price snapshot copied from MenuItem.price at creation time — NOT live-joined.
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.menu_item_id}"
