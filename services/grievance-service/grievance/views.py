"""Grievance endpoints (Task 6.5): create, list, retrieve.

``GrievanceCreateView`` creates a Ticket and emits ``grievance.created`` in the
SAME ``transaction.atomic()`` block — the transactional-outbox guarantee (state
and event commit or roll back together; nothing here talks to RabbitMQ directly,
``drain_outbox_task`` relays it later). ai-service (Task 7.x) consumes
``grievance.created``, scores the ``text``, and emits ``grievance.scored``.

The ``grievance.created`` payload carries ``raised_by`` (the recipient student)
and ``text`` so ai-service can score the text AND echo the recipient back in
``grievance.scored`` — letting notification-service notify the right user.

Reads are role/owner scoped: a plain student sees only their own tickets; a
warden/admin sees every ticket in their tenant. All queries go through
``Ticket.objects`` (tenant-scoped by TenantMiddleware), so there is never a
cross-tenant leak.
"""

import hashlib

from django.db import transaction
from django.utils import timezone
from grievance.models import MEDIA_RETENTION_DAYS, Ticket, TicketMedia
from grievance.serializers import (
    GrievanceCreateRequestSerializer,
    TicketMediaSerializer,
    TicketSerializer,
)
from rest_framework.generics import ListAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from suerp_common.envelope import fail, ok
from suerp_common.outbox import publish_event
from suerp_common.permissions import role_required
from suerp_common.tenancy import get_current_tenant

# Roles that may see/retrieve every ticket in their tenant (not just their own).
_PRIVILEGED_ROLES = {"warden", "admin"}


class GrievanceListCreateView(ListAPIView):
    """GET /api/v1/grievance — list; POST /api/v1/grievance — create."""

    serializer_class = TicketSerializer

    def get_queryset(self):
        # ``objects`` is tenant-scoped. A warden/admin sees all tickets in the
        # tenant; anyone else sees only the tickets they raised.
        qs = Ticket.objects.all().order_by("-created_at")
        role = getattr(self.request.user, "role", None)
        if role in _PRIVILEGED_ROLES:
            return qs
        return qs.filter(raised_by=self.request.user.id)

    def post(self, request):
        serializer = GrievanceCreateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid grievance request.", errors=serializer.errors, status=400)

        tenant_id = get_current_tenant()
        category = serializer.validated_data["category"]
        description = serializer.validated_data["description"]
        # raised_by is the JWT ``sub`` claim (the student raising the grievance).
        raised_by = request.user.id

        with transaction.atomic():
            ticket = Ticket.objects.create(
                tenant_id=tenant_id,
                raised_by=raised_by,
                category=category,
                description=description,
                status=Ticket.Status.OPEN,
            )
            # Transactional outbox: the event commits atomically with the
            # ticket. ``raised_by``/``text`` let ai-service score the text and
            # echo the recipient back in grievance.scored (see module docstring).
            publish_event(
                "grievance.created",
                tenant_id=tenant_id,
                payload={
                    "ticket_id": str(ticket.id),
                    "raised_by": str(ticket.raised_by),
                    "text": ticket.description,
                },
            )

        return ok(TicketSerializer(ticket).data, message="Grievance created.", status=201)


class GrievanceDetailView(APIView):
    """GET /api/v1/grievance/{id} — retrieve one (owner or warden/admin)."""

    def get(self, request, ticket_id):
        # Tenant-scoped lookup: a ticket from another tenant simply isn't found.
        try:
            ticket = Ticket.objects.get(id=ticket_id)
        except Ticket.DoesNotExist:
            return fail("Grievance not found.", status=404)

        role = getattr(request.user, "role", None)
        if role not in _PRIVILEGED_ROLES and str(ticket.raised_by) != str(request.user.id):
            return fail("Not permitted to view this grievance.", status=403)

        return ok(TicketSerializer(ticket).data)


#: Legal status moves, over Ticket.Status (open/escalated/in_progress/
#: resolved — there is no 'closed'). Resolution is terminal: a resolved
#: ticket never reopens, because the 7-day media purge (see the mobile
#: spec) is scheduled against its resolution time, and reopening would
#: promise evidence that is already on its way to being deleted.
_ALLOWED_STATUS_TRANSITIONS = {
    "open": {"escalated", "in_progress", "resolved"},
    "escalated": {"in_progress", "resolved"},
    "in_progress": {"resolved"},
    "resolved": set(),
}


class GrievanceStatusView(APIView):
    """PATCH /api/v1/grievance/<id>/status — warden moves a ticket forward."""

    permission_classes = [role_required("warden", "admin")]

    def patch(self, request, ticket_id):
        new_status = request.data.get("status")
        valid = set(_ALLOWED_STATUS_TRANSITIONS)
        if new_status not in valid:
            return fail(
                "Invalid status.",
                errors={"status": f"Must be one of {sorted(valid)}."},
                status=400,
            )

        # objects is tenant-scoped, so another tenant's ticket is simply
        # not found — no cross-tenant existence leak.
        try:
            ticket = Ticket.objects.get(id=ticket_id)
        except Ticket.DoesNotExist:
            return fail("Grievance not found.", status=404)

        if new_status not in _ALLOWED_STATUS_TRANSITIONS[ticket.status]:
            return fail(
                f"Cannot transition from '{ticket.status}' to '{new_status}'.",
                errors={"status": "Illegal transition."},
                status=400,
            )

        ticket.status = new_status
        ticket.save(update_fields=["status"])

        if new_status == Ticket.Status.RESOLVED:
            # Start the retention clock now rather than at upload time —
            # evidence on an unresolved ticket must never expire.
            ticket.media.filter(expires_at__isnull=True).update(
                expires_at=timezone.now() + timezone.timedelta(days=MEDIA_RETENTION_DAYS)
            )

        return ok(TicketSerializer(ticket).data, message="Status updated.")


class TicketMediaView(APIView):
    """POST/GET /api/v1/grievance/<id>/media — evidence attached to a ticket.

    Upload is restricted to the ticket's author: a photo of someone's room
    is not something another student should be able to bolt onto their
    complaint.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def _ticket_or_none(self, ticket_id):
        # ``objects`` is tenant-scoped, so another tenant's ticket is simply
        # not found — no cross-tenant existence leak.
        try:
            return Ticket.objects.get(id=ticket_id)
        except Ticket.DoesNotExist:
            return None

    def post(self, request, ticket_id):
        ticket = self._ticket_or_none(ticket_id)
        if ticket is None:
            return fail("Grievance not found.", status=404)

        if str(ticket.raised_by) != str(request.user.id):
            return fail("You can only attach media to your own grievance.", status=403)

        upload = request.FILES.get("file")
        if upload is None:
            return fail("A file is required.", status=400)

        # Hashed before storage so the audit trail can outlive the blob: once
        # the sweep deletes the file, this digest is all that proves what was
        # attached.
        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)

        media = TicketMedia.objects.create(
            tenant_id=get_current_tenant(),
            ticket=ticket,
            file=upload,
            sha256=digest.hexdigest(),
            captured_at=timezone.now(),
        )
        return ok(TicketMediaSerializer(media).data, message="Attached.", status=201)

    def get(self, request, ticket_id):
        ticket = self._ticket_or_none(ticket_id)
        if ticket is None:
            return fail("Grievance not found.", status=404)

        role = getattr(request.user, "role", None)
        if role not in _PRIVILEGED_ROLES and str(ticket.raised_by) != str(request.user.id):
            return fail("Not permitted to view this grievance.", status=403)

        return ok(TicketMediaSerializer(ticket.media.all(), many=True).data)
