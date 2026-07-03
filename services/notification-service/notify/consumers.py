"""Event fan-out consumers (Task 5.3) — the terminal saga step.

notification-service closes the saga demo loop: a student sees an in-app inbox
notification when their allocation confirms, their payment succeeds, or their
grievance is scored. It reacts to events from finance-, hostel-, and (future)
grievance-service by writing a ``Notification`` row for the recipient user.

This mirrors the reference EVENT CONSUMER pattern (see
services/finance-service/billing/consumers.py) with two differences:

* It binds ONE queue to several routing keys and dispatches by
  ``event["type"]`` (``dispatch_event`` below), because a single fan-out
  consumer is simpler to operate than one process per event type.
* It is a TERMINAL consumer: it never publishes a follow-on event, so there
  is no transactional outbox here. A plain ``Notification.all_objects.create``
  inside the ``@idempotent`` atomic block is sufficient (the decorator already
  runs the handler in one ``transaction.atomic()``).

Each handler:

1. Is wrapped in ``@idempotent`` (suerp_common.inbox) so at-least-once
   delivery never double-creates a notification — each ``event_id`` is
   recorded in ``ProcessedEvent`` and replays are a no-op.
2. Resolves ``tenant_id`` explicitly from the event envelope and writes
   through ``Notification.all_objects`` with that ``tenant_id`` set
   explicitly. Consumers run outside request context, so there is no
   TenantMiddleware-set tenant for the auto-scoping ``objects`` manager to
   filter by; using ``objects`` here would run unscoped. Explicit
   ``all_objects`` + explicit ``tenant_id`` makes every write's tenant scope
   visible at the call site and immune to leakage between deliveries. See the
   finance consumer docstring for the full rationale.
"""

from django.db import transaction
from notify.models import Notification
from suerp_common.inbox import idempotent


@idempotent
def handle_payment_success(event: dict) -> None:
    """``finance.payment.success`` -> notify the student their payment landed.

    Payload: ``{invoice_id, student_id, purpose, amount}``.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    student_id = payload["student_id"]
    purpose = payload.get("purpose", "")
    amount = payload.get("amount", "")

    with transaction.atomic():
        Notification.all_objects.create(
            tenant_id=tenant_id,
            user_id=student_id,
            title="Payment successful",
            body=f"Your {purpose} payment of {amount} was received.",
        )


@idempotent
def handle_allocation_confirmed(event: dict) -> None:
    """``hostel.allocation.confirmed`` -> notify the student their room is set.

    Payload: ``{allocation_id, student_id, room_id}``.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    student_id = payload["student_id"]

    with transaction.atomic():
        Notification.all_objects.create(
            tenant_id=tenant_id,
            user_id=student_id,
            title="Hostel room confirmed",
            body="Your hostel room allocation is confirmed.",
        )


@idempotent
def handle_grievance_scored(event: dict) -> None:
    """``grievance.scored`` -> notify the ticket owner of the assessment.

    Payload: ``{ticket_id, student_id|raised_by, sentiment, urgency}``.

    grievance-service is not built yet (Tasks 6.5/6.6). The recipient key is
    read defensively: ``student_id`` if present, else ``raised_by``; if neither
    is present the event is skipped gracefully (no notification, no error).

    NOTE for the grievance producer (Task 6.5/6.6): the ``grievance.scored``
    event MUST include the recipient user id in its payload (as ``student_id``
    or ``raised_by``), otherwise the owner will never be notified.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    recipient_id = payload.get("student_id") or payload.get("raised_by")
    if not recipient_id:
        # No recipient in the payload — nothing we can notify. Skip gracefully.
        return

    urgency = payload.get("urgency", "")

    with transaction.atomic():
        Notification.all_objects.create(
            tenant_id=tenant_id,
            user_id=recipient_id,
            title="Grievance update",
            body=f"Your grievance was assessed: urgency {urgency}.",
        )


# Route each delivered event to its handler by ``type``. The management command
# binds ONE queue to every key below and passes this dispatcher to
# ``make_consumer`` — see notify/management/commands/consume_events.py.
_HANDLERS = {
    "finance.payment.success": handle_payment_success,
    "hostel.allocation.confirmed": handle_allocation_confirmed,
    "grievance.scored": handle_grievance_scored,
}


def dispatch_event(event: dict) -> None:
    """Dispatch a delivered event to the handler for its ``type``.

    Unknown types (a routing-key/binding mismatch) are ignored — nothing to do.
    """
    handler = _HANDLERS.get(event.get("type"))
    if handler is None:
        return
    handler(event)
