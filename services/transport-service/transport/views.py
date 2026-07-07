"""Route/seat listing and booking endpoints (Task 6.3).

``BookingCreateView`` creates a seat booking. Double-booking the same seat on
the same schedule is prevented by ``Booking``'s partial UniqueConstraint on
``(tenant_id, schedule, seat_no)`` WHERE ``status=booked`` (see
transport.models): the whole flow runs in one ``transaction.atomic()`` with a
``select_for_update`` row lock on the schedule, and the create is guarded by
catching ``IntegrityError`` from the constraint — so two concurrent bookings of
the same seat serialize and exactly one wins (the other gets 400 "seat taken").

Bookings are idempotent by ``idempotency_key``: a retry with the same key
returns the already-created booking instead of making a second one.

On a successful booking the cached seat count for the schedule is invalidated
(see transport.services) so the next ``/seats`` read recomputes from the DB.
No event is published — a booking is terminal for now.
"""

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import ListAPIView
from rest_framework.views import APIView
from suerp_common.envelope import fail, ok
from suerp_common.permissions import role_required
from suerp_common.tenancy import get_current_tenant

from .models import Booking, BusSchedule, Route
from .serializers import (
    BookingRequestSerializer,
    BookingSerializer,
    BusScheduleSerializer,
    RouteSerializer,
)
from .services import get_available_seats, invalidate_seats


class RouteListView(ListAPIView):
    """GET /api/v1/transport/routes — tenant-scoped, paginated."""

    serializer_class = RouteSerializer

    def get_queryset(self):
        return Route.objects.all().order_by("-created_at")


class RouteSeatsView(APIView):
    """GET /api/v1/transport/routes/{id}/seats — available seats per schedule.

    Returns a list of ``{schedule_id, bus_no, capacity, available}`` for every
    schedule on the route, using the tenant-namespaced seat-availability cache.
    """

    def get(self, request, route_id):
        # ``objects`` is tenant-scoped, so a route from another tenant simply
        # isn't found — 404, no cross-tenant leak.
        try:
            route = Route.objects.get(id=route_id)
        except Route.DoesNotExist:
            return fail("Route not found.", status=404)

        schedules = BusSchedule.objects.filter(route=route).order_by("departure_time")
        data = [
            {
                "schedule_id": str(schedule.id),
                "bus_no": schedule.bus_no,
                "capacity": schedule.capacity,
                "available": get_available_seats(schedule),
            }
            for schedule in schedules
        ]
        return ok(data)


class BookingCreateView(APIView):
    """POST /api/v1/transport/bookings — book a seat on a schedule."""

    def post(self, request):
        serializer = BookingRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid booking request.", errors=serializer.errors, status=400)

        tenant_id = get_current_tenant()
        schedule_id = serializer.validated_data["schedule_id"]
        seat_no = serializer.validated_data["seat_no"]
        idempotency_key = serializer.validated_data.get("idempotency_key")
        # Derive student from the request body, else from the JWT ``sub`` claim.
        student_user_code = serializer.validated_data.get("student_user_code") or request.user.id

        with transaction.atomic():
            # Tenant-scoped lookup + row lock. A schedule from another tenant
            # isn't visible (404), so tenant B can't book on tenant A's bus.
            try:
                schedule = BusSchedule.objects.select_for_update().get(id=schedule_id)
            except BusSchedule.DoesNotExist:
                return fail("Schedule not found.", status=404)

            # Idempotency: a retry with the same key returns the same booking.
            if idempotency_key:
                existing = Booking.objects.filter(
                    schedule=schedule, idempotency_key=idempotency_key
                ).first()
                if existing is not None:
                    return ok(
                        BookingSerializer(existing).data,
                        message="Booking already exists.",
                        status=200,
                    )

            try:
                with transaction.atomic():
                    booking = Booking.objects.create(
                        tenant_id=tenant_id,
                        schedule=schedule,
                        student_user_code=student_user_code,
                        seat_no=seat_no,
                        status=Booking.Status.BOOKED,
                        idempotency_key=idempotency_key,
                    )
            except IntegrityError:
                # Partial-unique constraint tripped -> the seat is already held.
                return fail("Seat already taken.", status=400)

        invalidate_seats(tenant_id, schedule.id)
        return ok(BookingSerializer(booking).data, message="Booking created.", status=201)


class DriverScheduleListView(ListAPIView):
    """GET /api/v1/transport/schedules/mine — schedules for the acting driver.

    A driver sees only their own schedules (``driver_id == JWT sub``); an admin
    sees every schedule in the tenant.
    """

    serializer_class = BusScheduleSerializer
    permission_classes = [role_required("driver", "admin")]

    def get_queryset(self):
        qs = BusSchedule.objects.select_related("route").order_by("departure_time")
        if getattr(self.request.user, "role", None) != "admin":
            qs = qs.filter(driver_id=self.request.user.id)
        return qs


class ScheduleBookingsView(ListAPIView):
    """GET /api/v1/transport/schedules/<schedule_id>/bookings — bookings on a
    schedule. A driver may only read bookings for a schedule they own (403
    otherwise); an admin may read any schedule in the tenant."""

    serializer_class = BookingSerializer
    permission_classes = [role_required("driver", "admin")]

    def get_queryset(self):
        # ``objects`` is tenant-scoped, so a schedule from another tenant isn't
        # found -> 404, no cross-tenant leak.
        schedule = get_object_or_404(BusSchedule, id=self.kwargs["schedule_id"])
        role = getattr(self.request.user, "role", None)
        if role != "admin" and str(schedule.driver_id) != str(self.request.user.id):
            raise PermissionDenied("You do not own this schedule.")
        return Booking.objects.filter(schedule=schedule).order_by("seat_no")
