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

from decimal import Decimal

from billing.models import FeeStructure, Invoice
from django.db import transaction
from suerp_common.inbox import idempotent
from suerp_common.outbox import publish_event

HOSTEL_FEE_AMOUNT = Decimal("5000.00")


def _resolve_hostel_fee_amount(tenant_id, fee_structure_id) -> Decimal:
    """Look up the warden-chosen FeeStructure's amount, falling back to the
    hardcoded default when no fee_structure_id was passed (legacy direct-
    allocate path — AllocateView/AllocateBulkView don't collect a fee choice
    at all) or when the id doesn't resolve (deleted/cross-tenant/typo'd —
    fail open to the old default rather than blocking invoice creation
    entirely, since this consumer has no way to surface an error back to the
    warden who already approved the request).
    """
    if not fee_structure_id:
        return HOSTEL_FEE_AMOUNT

    fee_structure = FeeStructure.all_objects.filter(
        tenant_id=tenant_id, id=fee_structure_id
    ).first()
    return fee_structure.amount if fee_structure is not None else HOSTEL_FEE_AMOUNT


@idempotent
def handle_allocation_requested(event: dict) -> None:
    """Handle ``hostel.allocation.requested``: create a pending hostel Invoice.

    Expects ``event["payload"]`` to contain ``allocation_id``, ``student_id``,
    ``room_id``, and (new) ``fee_structure_id``/``university_name`` — both
    optional, present only when the allocation came from warden room-request
    approval rather than the direct AllocateView/AllocateBulkView path.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    student_id = payload["student_id"]
    allocation_id = payload["allocation_id"]
    fee_structure_id = payload.get("fee_structure_id")
    university_name = payload.get("university_name") or ""

    amount = _resolve_hostel_fee_amount(tenant_id, fee_structure_id)

    with transaction.atomic():
        invoice = Invoice.all_objects.create(
            tenant_id=tenant_id,
            student_id=student_id,
            amount=amount,
            purpose="hostel",
            status=Invoice.Status.PENDING,
            university_name=university_name,
        )

        publish_event(
            "finance.invoice.created",
            tenant_id=tenant_id,
            payload={
                "invoice_id": str(invoice.id),
                "student_id": student_id,
                "allocation_id": allocation_id,
                "amount": str(amount),
                "purpose": "hostel",
            },
        )
