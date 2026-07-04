"""Allocate and listing endpoints (Task 4.8).

``AllocateView`` STARTS the hostel-allocation saga: it reserves a room
(``occupied_count += 1``) and creates a pending ``Allocation`` in the SAME
``transaction.atomic()`` block as the ``hostel.allocation.requested`` outbox
event — the transactional-outbox guarantee (state and event commit or roll
back together; nothing here talks to RabbitMQ directly,
``drain_outbox_task`` relays it later). finance-service's consumer (see
services/finance-service/billing/consumers.py) reacts to this event by
creating a pending hostel-fee invoice.

``select_for_update()`` on the Room row prevents concurrent over-allocation:
two simultaneous allocate calls against the same last-open bed will
serialize on the row lock, so the second one observes the incremented
``occupied_count`` and correctly 400s instead of double-booking.
"""

from django.db.models import F
from hostel.models import Allocation, Room
from hostel.serializers import AllocateRequestSerializer, AllocationSerializer, RoomSerializer
from hostel.services import RoomFullError, create_allocation
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from suerp_common.envelope import fail, ok
from suerp_common.permissions import role_required
from suerp_common.tenancy import get_current_tenant


class AvailableRoomsView(ListAPIView):
    """GET /api/v1/hostel/rooms/available — tenant-scoped, paginated."""

    serializer_class = RoomSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Filter in the DB (not Python) so this scales — ``is_available`` is a
        # computed property, but its condition maps directly to a queryset
        # filter, keeping pagination's LIMIT/OFFSET push-down intact.
        return Room.objects.filter(occupied_count__lt=F("capacity")).order_by("room_no")


class AllocationListView(ListAPIView):
    """GET /api/v1/hostel/allocations — tenant-scoped, paginated."""

    serializer_class = AllocationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Allocation.objects.all().order_by("-created_at")


class AllocateView(APIView):
    permission_classes = [role_required("warden", "admin")]

    def post(self, request):
        serializer = AllocateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid allocation request.", errors=serializer.errors, status=400)

        room_id = serializer.validated_data["room_id"]
        student_id = serializer.validated_data["student_id"]

        try:
            allocation = create_allocation(room_id, student_id, get_current_tenant())
        except RoomFullError:
            return fail("Room at full capacity.", status=400)

        return ok(
            AllocationSerializer(allocation).data,
            message="Allocation created.",
            status=201,
        )
