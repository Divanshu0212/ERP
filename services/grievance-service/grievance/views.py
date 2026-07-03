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

from django.db import transaction
from grievance.models import Ticket
from grievance.serializers import GrievanceCreateRequestSerializer, TicketSerializer
from rest_framework.generics import ListAPIView
from rest_framework.views import APIView
from suerp_common.envelope import fail, ok
from suerp_common.outbox import publish_event
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
