"""Event consumers (Task 6.3) — activate a seasonal Pass on payment success.

transport-service reacts to finance-service's ``finance.payment.success``: when
a student pays for a bus pass, the payment event carries a ``purpose``. If the
purpose is a transport pass ("transport"/"bus_pass"), this activates a seasonal
``Pass`` for that student (create-or-update ``active=True``). Payments for other
purposes (e.g. "hostel") land on the same queue but are skipped gracefully.

This follows the reference consumer pattern in
services/finance-service/billing/consumers.py and
services/hostel-service/hostel/consumers.py:

1. ``@idempotent`` (suerp_common.inbox) outermost — at-least-once delivery
   means duplicates happen; each ``event_id`` is recorded in
   ``ProcessedEvent`` so replays are a no-op (one active pass, no error).
2. Tenant resolved explicitly from ``event["tenant_id"]`` and every query uses
   ``Pass.all_objects``: consumers run as a standalone process (``manage.py
   consume_events``), never inside a Django request, so there is no ambient
   tenant for the auto-scoping ``TenantManager`` to filter by.
3. The state change runs in a ``transaction.atomic()`` block. (No event is
   published back out here — pass activation is terminal.)
"""

import logging

from django.db import transaction
from suerp_common.inbox import idempotent
from transport.models import Pass

logger = logging.getLogger(__name__)

# Payment purposes that mean "this payment buys a transport pass".
TRANSPORT_PURPOSES = {"transport", "bus_pass"}


@idempotent
def handle_payment_success(event: dict) -> None:
    """Handle ``finance.payment.success``: activate a seasonal Pass.

    Expects ``event["payload"]`` to contain ``student_user_code`` and
    ``purpose``, and ``event["tenant_id"]`` at the top level of the envelope.
    Non-transport purposes are skipped (no Pass created). ``route_id``/
    ``valid_from``/``valid_to`` are optional in the payload.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    purpose = payload.get("purpose")

    if purpose not in TRANSPORT_PURPOSES:
        # Another service's payment (e.g. hostel) delivered on the shared
        # routing key — not ours to act on.
        return

    student_user_code = payload["student_user_code"]
    route_id = payload.get("route_id")
    valid_from = payload.get("valid_from")
    valid_to = payload.get("valid_to")

    with transaction.atomic():
        # Create-or-update: one active seasonal pass per (tenant, student).
        # ``all_objects`` because there's no ambient tenant in the consumer.
        defaults = {"active": True}
        if route_id is not None:
            defaults["route_id"] = route_id
        if valid_from is not None:
            defaults["valid_from"] = valid_from
        if valid_to is not None:
            defaults["valid_to"] = valid_to

        _pass, created = Pass.all_objects.update_or_create(
            tenant_id=tenant_id,
            student_user_code=student_user_code,
            defaults=defaults,
        )
        if created:
            logger.info(
                "Activated new transport Pass for student=%s tenant=%s",
                student_user_code,
                tenant_id,
            )
        else:
            logger.info(
                "Reactivated transport Pass for student=%s tenant=%s",
                student_user_code,
                tenant_id,
            )


def dispatch(event: dict) -> None:
    """Route an event to its handler by ``event["type"]``.

    ``suerp_common.events.make_consumer`` takes a single handler; this thin
    dispatcher keeps the door open for binding more routing keys later.
    """
    handlers = {
        "finance.payment.success": handle_payment_success,
    }
    handler = handlers.get(event["type"])
    if handler is None:
        logger.warning("No handler registered for event type=%s", event["type"])
        return
    handler(event)
