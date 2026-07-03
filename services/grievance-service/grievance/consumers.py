"""Event consumers (Task 6.6) — apply AI scoring and auto-escalate.

grievance-service STARTED this chain (Task 6.5, ``GrievanceCreateView`` ->
``grievance.created``). ai-service (Task 7.x) consumes that event, scores the
grievance ``text``, and emits ``grievance.scored`` carrying the sentiment,
urgency, AND an echoed ``raised_by`` (the recipient student). This module
reacts to ``grievance.scored`` by stamping the sentiment/urgency onto the
Ticket and auto-escalating when the urgency is high/critical.

CONTRACT with ai-service (PRODUCER of grievance.scored) and notification-service
(also a CONSUMER of grievance.scored): ai-service MUST echo ``raised_by`` in the
grievance.scored payload so notification-service can notify the right user. This
service does NOT re-publish an event — grievance is TERMINAL for this chain
(notification-service consumes grievance.scored directly).

Follows the reference consumer pattern in
services/finance-service/billing/consumers.py and
services/transport-service/transport/consumers.py:

1. ``@idempotent`` (suerp_common.inbox) outermost — at-least-once delivery means
   duplicates happen; each ``event_id`` is recorded in ``ProcessedEvent`` so
   replays are a no-op. The state application (setting the same fields) is also
   naturally idempotent if applied twice.
2. Tenant resolved explicitly from ``event["tenant_id"]`` and the query uses
   ``Ticket.all_objects``: consumers run as a standalone process (``manage.py
   consume_events``), never inside a Django request, so there is no ambient
   tenant for the auto-scoping ``TenantManager`` to filter by.
3. The state change runs in a ``transaction.atomic()`` block. (No event is
   published back out here — scoring is terminal for grievance.)
"""

import logging

from django.db import transaction
from grievance.models import Ticket
from suerp_common.inbox import idempotent

logger = logging.getLogger(__name__)

# Urgency levels that trigger auto-escalation of the ticket.
ESCALATION_URGENCIES = {"high", "critical"}


@idempotent
def handle_grievance_scored(event: dict) -> None:
    """Handle ``grievance.scored``: apply sentiment/urgency, auto-escalate.

    Expects ``event["payload"]`` to contain ``ticket_id``, ``sentiment``,
    ``urgency`` and ``raised_by`` (echoed recipient), and ``event["tenant_id"]``
    at the top level of the envelope. If the ticket can't be found for this
    tenant (e.g. a stray event or a cross-tenant ticket_id), log and return
    rather than crash.

    When ``urgency`` is high/critical the ticket is escalated (status ->
    escalated). Assigning the escalated ticket to a SPECIFIC warden is a
    follow-up (grievance-service has no warden directory here); for now
    ``assigned_to`` is left null and only the status is escalated.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    ticket_id = payload["ticket_id"]
    sentiment = payload.get("sentiment")
    urgency = payload.get("urgency")

    with transaction.atomic():
        try:
            ticket = Ticket.all_objects.select_for_update().get(tenant_id=tenant_id, id=ticket_id)
        except Ticket.DoesNotExist:
            logger.warning(
                "grievance.scored for unknown ticket_id=%s tenant_id=%s",
                ticket_id,
                tenant_id,
            )
            return

        ticket.sentiment_score = sentiment
        ticket.urgency = urgency
        update_fields = ["sentiment_score", "urgency"]

        if urgency in ESCALATION_URGENCIES:
            # Auto-escalate. Assignment to a specific warden is a follow-up;
            # assigned_to stays null for now (no warden directory here).
            ticket.status = Ticket.Status.ESCALATED
            update_fields.append("status")

        ticket.save(update_fields=update_fields)


def dispatch(event: dict) -> None:
    """Route an event to its handler by ``event["type"]``.

    ``suerp_common.events.make_consumer`` takes a single handler; this thin
    dispatcher keeps the door open for binding more routing keys later.
    """
    handlers = {
        "grievance.scored": handle_grievance_scored,
    }
    handler = handlers.get(event["type"])
    if handler is None:
        logger.warning("No handler registered for event type=%s", event["type"])
        return
    handler(event)
