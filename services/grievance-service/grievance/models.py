"""Grievance domain models: Ticket, TicketComment.

Both are ``suerp_common.tenancy.TenantModel`` subclasses — grievance-service is
a normal resource service. ``objects`` is transparently scoped to the active
tenant; ``all_objects`` bypasses scoping for system operations (event consumers
that resolve tenant from the event payload).

``Ticket.raised_by`` (the student) and ``Ticket.assigned_to`` (a warden/admin)
are bare user_code strings, not ForeignKeys: auth-service owns those User rows
in its own database (DB-per-service), so grievance-service can only ever hold
an opaque reference to them, never a real FK. ``TicketComment.ticket`` IS a real
ForeignKey since both models live in this same database.
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class Ticket(TenantModel):
    class Category(models.TextChoices):
        HOSTEL = "hostel", "Hostel"
        ACADEMIC = "academic", "Academic"
        HARASSMENT = "harassment", "Harassment"
        IT = "it", "IT"
        RAGGING = "ragging", "Ragging"

    class Urgency(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ESCALATED = "escalated", "Escalated"
        IN_PROGRESS = "in_progress", "In Progress"
        RESOLVED = "resolved", "Resolved"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Reference to auth-service's User table (the student who raised the
    # grievance), by user_code. No cross-service FK (DB-per-service) — bare
    # opaque string.
    raised_by = models.CharField(max_length=30)
    # Free-form category label (not constrained to Category.choices at the DB
    # level so new categories can be added without a migration).
    category = models.CharField(max_length=50)
    description = models.TextField()
    # Filled later by ai-service via the grievance.scored event.
    sentiment_score = models.FloatField(null=True, blank=True)
    urgency = models.CharField(max_length=20, choices=Urgency.choices, null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    # Reference to auth-service's User table (a warden/admin), by user_code.
    assigned_to = models.CharField(max_length=30, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="ticket_tenant_status"),
            models.Index(fields=["tenant_id", "raised_by"], name="ticket_tenant_raised_by"),
        ]

    def __str__(self):
        return f"Ticket {self.id} ({self.category}, {self.status})"


#: How long evidence survives after a ticket is resolved. Long enough that a
#: student who disagrees with the resolution can still point at the photo;
#: short enough that the platform is not indefinitely holding images of
#: people's rooms. See the mobile spec's retention rule.
MEDIA_RETENTION_DAYS = 7


class TicketMedia(TenantModel):
    """A photo or short video attached to a grievance.

    The blob is deliberately temporary and the metadata is not. Seven days
    after the ticket is resolved a sweep deletes the file and stamps
    ``purged_at``, leaving ``sha256`` and ``captured_at`` behind — so the log
    can still say "three attachments, purged on the 9th" without the platform
    holding the images forever.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="media")
    file = models.FileField(upload_to="grievance-media/", blank=True)
    sha256 = models.CharField(max_length=64)
    captured_at = models.DateTimeField()
    #: Null until the ticket resolves — an open ticket's evidence never expires.
    expires_at = models.DateTimeField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["expires_at", "purged_at"], name="media_purge_sweep"),
        ]

    def __str__(self):
        state = "purged" if self.purged_at else "held"
        return f"media({self.ticket_id}, {state})"


class TicketComment(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="comments")
    comment_by = models.CharField(max_length=30)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comment {self.id} on ticket {self.ticket_id}"
