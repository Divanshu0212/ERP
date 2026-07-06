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


class PaymentOutcome(TenantModel):
    """Records the OUTCOME of a finance payment event, keyed by ``invoice_id``.

    Exists to make the allocation saga's correlation ORDER-INDEPENDENT.
    ``finance.invoice.created`` (which stamps ``Allocation.invoice_id``) and
    ``finance.payment.success``/``finance.payment.failed`` (which carry only
    ``invoice_id``) come from two independent finance code paths and are
    delivered async, so they can arrive at hostel out of order. If a payment
    event lands before its invoice.created has stamped the allocation, the
    lookup by ``invoice_id`` finds nothing and the outcome would be lost. To
    avoid that, whichever payment event arrives first persists its outcome
    here; whichever correlation event lands (``handle_invoice_created``)
    reconciles by applying any not-yet-``applied`` outcome for that invoice.

    The unique constraint on ``(tenant_id, invoice_id)`` makes a duplicate
    outcome a no-op at the DB level (one payment result per invoice).
    """

    class Outcome(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Bare UUID: finance-service owns the Invoice row in its own database.
    invoice_id = models.UUIDField(db_index=True)
    outcome = models.CharField(max_length=20, choices=Outcome.choices)
    # True once the outcome has been applied to its Allocation (confirmed or
    # released). Set False by the deferred path (payment event arrived first)
    # and flipped True by handle_invoice_created when it reconciles.
    applied = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "invoice_id"], name="payment_outcome_tenant_invoice_unique"
            ),
        ]

    def __str__(self):
        return f"PaymentOutcome {self.invoice_id} ({self.outcome}, applied={self.applied})"


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


class RoomRequest(TenantModel):
    """A student's request to be allocated a specific room, awaiting warden
    approval. Distinct from ``Allocation`` — this is the pre-approval intent;
    approving one calls ``create_allocation()`` (hostel/services.py), which
    creates the actual ``Allocation`` and starts the existing payment saga
    unchanged.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student_id = models.UUIDField()
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="requests")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    requested_on = models.DateTimeField(auto_now_add=True)
    decided_on = models.DateTimeField(null=True, blank=True)
    # Reference to auth-service's User table (the warden who approved/rejected).
    # Bare UUID — no cross-service FK (DB-per-service).
    decided_by = models.UUIDField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["-requested_on"]
        constraints = [
            # A student can hold at most ONE pending request per room. Scoped to
            # status="pending" so a rejected/approved request never blocks a
            # later re-request for the same room, but a duplicate PENDING one
            # (double-submit, replay) is rejected at the DB level.
            models.UniqueConstraint(
                fields=["tenant_id", "student_id", "room"],
                condition=models.Q(status="pending"),
                name="roomrequest_one_pending_per_student_room",
            ),
        ]

    def __str__(self):
        return f"RoomRequest {self.id} ({self.status})"


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


class AllocationImportBatch(TenantModel):
    """One warden-initiated bulk-allocation upload (CSV or XLSX).

    ``success_count``/``fail_count``/``skipped_count`` are denormalized onto the
    batch (rather than always aggregating ``rows``) so the Import Logs list view
    can show them without an extra query per batch.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Reference to auth-service's User table (the warden/admin who uploaded).
    # Bare UUID — no cross-service FK (DB-per-service).
    uploaded_by = models.UUIDField()
    filename = models.CharField(max_length=255)
    total_rows = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    fail_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"ImportBatch {self.id} ({self.filename})"


class AllocationImportRow(TenantModel):
    """One row's outcome within an AllocationImportBatch."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(AllocationImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()
    room_id_raw = models.CharField(max_length=255)
    student_email_raw = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices)
    error_message = models.CharField(max_length=500, blank=True, default="")
    allocation = models.ForeignKey(
        Allocation, on_delete=models.SET_NULL, null=True, blank=True, related_name="import_rows"
    )

    class Meta:
        ordering = ["row_number"]

    def __str__(self):
        return f"ImportRow {self.row_number} of batch {self.batch_id} ({self.status})"
