"""Notification domain model: the in-app inbox row.

``Notification`` is a ``suerp_common.tenancy.TenantModel`` subclass —
notification-service is a normal resource service. ``objects`` is transparently
scoped to the active tenant; ``all_objects`` bypasses scoping for system
operations (event consumers that resolve tenant from the event payload).

``user_code`` is a bare string, not a ForeignKey: auth-service owns the User
table in its own database (DB-per-service), so notification-service can only
ever hold an opaque reference to the recipient, never a real FK.
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class Notification(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Recipient. Reference to auth-service's User table — bare user_code
    # string (DB-per-service), no cross-service FK.
    user_code = models.CharField(max_length=30)
    title = models.CharField(max_length=255)
    body = models.TextField()
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["tenant_id", "user_code", "read"],
                name="notif_tenant_user_read",
            ),
        ]

    def __str__(self):
        return f"Notification {self.id} -> {self.user_code}"


class PushDevice(TenantModel):
    """Push tokens, projected into this service.

    auth-service owns the authoritative Device row; this is a local copy
    populated by the app registering its token here after login, because
    DB-per-service means this service cannot join across to it.

    ``is_stale`` is set when the provider reports the token is dead
    (uninstalled app, reset device). Stale rows are kept rather than deleted:
    the same token can come back on re-registration, and the row is the only
    record that this device was ever reachable.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_code = models.CharField(max_length=30)
    push_token = models.CharField(max_length=255, unique=True)
    is_stale = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["tenant_id", "user_code", "is_stale"],
                name="device_tenant_user_live",
            ),
        ]

    def __str__(self):
        return f"PushDevice {self.user_code} ({'stale' if self.is_stale else 'live'})"
