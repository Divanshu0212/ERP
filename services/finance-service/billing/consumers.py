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
   objects``) to filter by. NOTE: with no contextvar set, ``TenantManager``
   does NOT fail safe — it returns an *unfiltered, cross-tenant* queryset
   (this is deliberate, for migrations/system tasks). So using ``objects`` in
   a consumer would silently read/write across every tenant. That makes the
   explicit approach below not just tidier but mandatory. The chosen —
   and required — approach is to
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

import logging

from billing.models import FeeStructure, Invoice
from django.db import transaction
from suerp_common.inbox import idempotent
from suerp_common.outbox import publish_event

logger = logging.getLogger(__name__)


@idempotent
def handle_allocation_requested(event: dict) -> None:
    """Handle ``hostel.allocation.requested``: create a pending hostel Invoice.

    Expects ``event["payload"]`` to contain ``allocation_id``,
    ``student_user_code``, ``room_id``, ``fee_structure_id``, ``due_date``,
    and ``university_name``. hostel-service's create_allocation() only ever
    publishes this event when a fee was actually chosen — a direct/no-fee
    allocation confirms synchronously in hostel-service and never publishes
    this event at all, so every delivery here always carries a real
    fee_structure_id/due_date pair.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    student_user_code = payload["student_user_code"]
    allocation_id = payload["allocation_id"]
    fee_structure_id = payload["fee_structure_id"]
    due_date = payload.get("due_date")
    university_name = payload.get("university_name") or ""

    fee_structure = FeeStructure.all_objects.filter(
        tenant_id=tenant_id, id=fee_structure_id
    ).first()
    if fee_structure is None:
        logger.warning(
            "hostel.allocation.requested for unresolvable fee_structure_id=%s tenant_id=%s "
            "allocation_id=%s — skipping invoice creation",
            fee_structure_id,
            tenant_id,
            allocation_id,
        )
        return
    amount = fee_structure.amount

    with transaction.atomic():
        invoice = Invoice.all_objects.create(
            tenant_id=tenant_id,
            student_user_code=student_user_code,
            amount=amount,
            purpose="hostel",
            status=Invoice.Status.PENDING,
            university_name=university_name,
            due_date=due_date,
        )

        publish_event(
            "finance.invoice.created",
            tenant_id=tenant_id,
            payload={
                "invoice_id": str(invoice.id),
                "student_user_code": student_user_code,
                "allocation_id": allocation_id,
                "amount": str(amount),
                "purpose": "hostel",
            },
        )
