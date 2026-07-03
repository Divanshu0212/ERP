"""Notification domain model: the in-app inbox row.

``Notification`` is a ``suerp_common.tenancy.TenantModel`` subclass —
notification-service is a normal resource service. ``objects`` is transparently
scoped to the active tenant; ``all_objects`` bypasses scoping for system
operations (event consumers that resolve tenant from the event payload).

``user_id`` is a bare UUID, not a ForeignKey: auth-service owns the User table
in its own database (DB-per-service), so notification-service can only ever
hold an opaque reference to the recipient, never a real FK.
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class Notification(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Recipient. Reference to auth-service's User table — no cross-service FK
    # (DB-per-service), this is a bare, opaque UUID.
    user_id = models.UUIDField()
    title = models.CharField(max_length=255)
    body = models.TextField()
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["tenant_id", "user_id", "read"],
                name="notif_tenant_user_read",
            ),
        ]

    def __str__(self):
        return f"Notification {self.id} -> {self.user_id}"
