"""Event consumers (Task 4.5) — the saga step that reacts to hostel allocation.

This is the reference EVENT CONSUMER pattern every later consumer in this
monorepo copies:

1. ``@idempotent`` (suerp_common.inbox) wraps the handler so at-least-once
   delivery (guaranteed by the transactional outbox on the *producer* side —
   see suerp_common.outbox) never double-processes an event: each
   ``event_id`` is recorded in ``ProcessedEvent`` and replays are a no-op.
2. Tenant handling: consumers run as a standalone process (``manage.py
   consume_events``), never inside a Django request, so there is no
   ``TenantMiddleware`` to populate ``suerp_common.tenancy``'s contextvar and
   no ambient tenant for the auto-scoping ``TenantManager`` (``Invoice.
   objects``) to filter by. The chosen — and recommended — approach is to
   resolve ``tenant_id`` explicitly from the event envelope and write through
   ``Invoice.all_objects`` (which bypasses tenant scoping) with that
   ``tenant_id`` set explicitly on every created row. This is more robust
   than the alternative (``set_current_tenant`` + ``objects``) because it has
   no dependency on contextvar state being managed correctly across a
   long-lived consumer loop that processes many tenants' events back to
   back — get a reset wrong (e.g. an exception path that skips the
   ``finally``) and the *next* event would silently run under the *previous*
   event's tenant. Explicit ``all_objects`` + explicit ``tenant_id`` makes
   every query's tenant scope visible at the call site and immune to leakage
   between deliveries.
3. Transactional outbox on the way out: the new ``Invoice`` and the
   ``finance.invoice.created`` ``OutboxEvent`` are created in the SAME
   ``transaction.atomic()`` block, so a crash between them is impossible —
   either both commit or neither does. A separate drain process (Celery beat,
   see ``billing.tasks.drain_outbox_task``) relays the outbox row to
   RabbitMQ later; this handler never talks to the broker directly.

Later consumers should follow the same three points: ``@idempotent`` first,
resolve tenant from the event payload/envelope and use ``all_objects``, and
keep the write + ``publish_event`` call in one atomic block.
"""

from decimal import Decimal

from billing.models import Invoice
from django.db import transaction
from suerp_common.inbox import idempotent
from suerp_common.outbox import publish_event

HOSTEL_FEE_AMOUNT = Decimal("5000.00")


@idempotent
def handle_allocation_requested(event: dict) -> None:
    """Handle ``hostel.allocation.requested``: create a pending hostel Invoice.

    Expects ``event["payload"]`` to contain ``allocation_id``, ``student_id``,
    and ``room_id`` (room_id is unused here but part of the envelope), and
    ``event["tenant_id"]`` at the top level of the envelope.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    student_id = payload["student_id"]
    allocation_id = payload["allocation_id"]

    with transaction.atomic():
        invoice = Invoice.all_objects.create(
            tenant_id=tenant_id,
            student_id=student_id,
            amount=HOSTEL_FEE_AMOUNT,
            purpose="hostel",
            status=Invoice.Status.PENDING,
        )

        publish_event(
            "finance.invoice.created",
            tenant_id=tenant_id,
            payload={
                "invoice_id": str(invoice.id),
                "student_id": student_id,
                "allocation_id": allocation_id,
                "amount": str(HOSTEL_FEE_AMOUNT),
                "purpose": "hostel",
            },
        )
