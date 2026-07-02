"""Hostel domain models: Block, Room, Allocation, LeaveRequest, Complaint.

All five are ``suerp_common.tenancy.TenantModel`` subclasses — hostel-service
is a normal resource service (unlike auth-service, which is the identity
authority and has documented reasons to deviate from TenantModel). ``objects``
is transparently scoped to the active tenant; ``all_objects`` bypasses scoping
for system operations.

``Block.warden_id``, ``Allocation.student_id``/``invoice_id``,
``LeaveRequest.student_id``, and ``Complaint.student_id`` are bare UUIDs, not
ForeignKeys: auth-service/student-service and finance-service own those rows
in their own databases (DB-per-service), so hostel-service can only ever hold
an opaque reference to them, never a real FK. ``Room.block`` and
``Allocation.room``/``Complaint.room`` ARE real ForeignKeys since Block/Room
live in this same database.
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class Block(TenantModel):
    class GenderType(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    gender_type = models.CharField(max_length=1, choices=GenderType.choices)
    # Reference to auth-service's User table (the warden). No cross-service FK
    # (DB-per-service) — this is a bare, opaque UUID.
    warden_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Room(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name="rooms")
    room_no = models.CharField(max_length=50)
    capacity = models.PositiveSmallIntegerField(default=2)
    occupied_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "block", "room_no"], name="room_tenant_block_roomno_unique"
            ),
        ]

    @property
    def is_available(self) -> bool:
        return self.occupied_count < self.capacity

    def __str__(self):
        return f"{self.block.name}/{self.room_no}"


class Allocation(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        RELEASED = "released", "Released"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="allocations")
    # Reference to student-service's Student table. No cross-service FK
    # (DB-per-service) — this is a bare, opaque UUID.
    student_id = models.UUIDField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    allocated_on = models.DateTimeField(auto_now_add=True)
    vacated_on = models.DateField(null=True, blank=True)
    # Filled in when finance-service emits finance.invoice.created, for
    # correlating this allocation with its hostel-fee invoice. Bare UUID
    # (finance-service owns the Invoice row in its own database).
    invoice_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="allocation_tenant_status"),
            models.Index(fields=["tenant_id", "student_id"], name="allocation_tenant_student"),
        ]

    def __str__(self):
        return f"Allocation {self.id} ({self.status})"


class LeaveRequest(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student_id = models.UUIDField()
    from_date = models.DateField()
    to_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"LeaveRequest {self.id} ({self.status})"


class Complaint(TenantModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        RESOLVED = "resolved", "Resolved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student_id = models.UUIDField()
    room = models.ForeignKey(
        Room, on_delete=models.SET_NULL, related_name="complaints", null=True, blank=True
    )
    description = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Complaint {self.id} ({self.status})"
