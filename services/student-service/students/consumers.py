"""user.registered consumer — the async half of bulk/single student creation.

auth-service creates the User row synchronously (see
services/auth-service/accounts/views.py:UserBulkCreateView /
UserAdminView / RegisterView) and publishes user.registered for every role,
not just students. This consumer reacts to that event and creates the
matching StudentProfile — but only when payload["role"] == "student"; every
other role's registration is a silent no-op here, since student-service has
nothing to do with wardens/faculty/etc.

Follows the same three points as the reference consumer pattern in
services/hostel-service/hostel/consumers.py:

1. @idempotent (suerp_common.inbox) outermost — at-least-once delivery means
   duplicates happen.
2. Tenant resolved explicitly from event["tenant_id"], StudentProfile.all_objects
   used (never the tenant-scoped StudentProfile.objects) — this consumer runs as
   a standalone process (manage.py consume_events), never inside a Django
   request, so there's no ambient tenant for the auto-scoping TenantManager.
3. get_or_create on (tenant_id, user_code) as a second idempotency layer,
   beyond @idempotent's event_id tracking — guards against two distinct
   events (different event_id) that both target the same student, which
   @idempotent alone cannot catch. Relies on the unique_together constraint
   added in students/models.py.
"""

import logging

from django.db import transaction
from students.models import StudentProfile
from suerp_common.inbox import idempotent

logger = logging.getLogger(__name__)


@idempotent
def handle_user_registered(event: dict) -> None:
    """Handle user.registered: create a StudentProfile iff role == student."""
    payload = event["payload"]
    if payload.get("role") != "student":
        return

    tenant_id = event["tenant_id"]
    with transaction.atomic():
        StudentProfile.all_objects.get_or_create(
            tenant_id=tenant_id,
            user_code=payload["user_code"],
            defaults={
                "department": payload.get("department", ""),
                "batch": payload.get("batch", ""),
                "semester": payload.get("semester", 1),
            },
        )


def dispatch(event: dict) -> None:
    """Route an event to its handler by event['type'].

    Only one routing key today (user.registered), but kept as a dispatcher
    — not a bare handler reference — for the same reason
    hostel.consumers.dispatch is: a second event type can be added later
    without restructuring the consume_events command.
    """
    handlers = {
        "user.registered": handle_user_registered,
    }
    handler = handlers.get(event["type"])
    if handler is None:
        logger.warning("No handler registered for event type=%s", event["type"])
        return
    handler(event)
