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

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from suerp_common.envelope import fail, ok
from suerp_common.permissions import role_required
from suerp_common.tenancy import get_current_tenant

from .models import Booking, Breadcrumb, BusSchedule, Route, Trip
from .serializers import (
    BookingRequestSerializer,
    BookingSerializer,
    BreadcrumbBatchSerializer,
    BusScheduleSerializer,
    RouteSerializer,
    TripSerializer,
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

        schedules = list(BusSchedule.objects.filter(route=route).order_by("departure_time"))

        # Which seats are gone, per schedule. A bare available count tells a
        # student how many seats are left but not which ones, so a seat picker
        # cannot render without this — and letting them tap a taken seat only
        # to be refused by the uniqueness constraint is a worse experience than
        # showing it as unavailable up front.
        taken_by_schedule = {schedule.id: [] for schedule in schedules}
        for schedule_id, seat_no in Booking.objects.filter(
            schedule__in=schedules, status="booked"
        ).values_list("schedule_id", "seat_no"):
            taken_by_schedule[schedule_id].append(seat_no)

        data = [
            {
                "schedule_id": str(schedule.id),
                "bus_no": schedule.bus_no,
                # Without this the student sees several buses on a route with
                # no way to tell which one leaves when.
                "departure_time": schedule.departure_time.isoformat(),
                "capacity": schedule.capacity,
                "available": get_available_seats(schedule),
                "taken": sorted(taken_by_schedule[schedule.id]),
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


#: A position older than a minute is worse than no position, because a student
#: would trust a stale dot on the map.
LIVE_POSITION_TTL_SECONDS = 60


def _live_key(tenant_id, route_id) -> str:
    """Tenant-namespaced, matching this service's seat-cache key convention
    (see transport.services.seats_cache_key) so no tenant can read another's
    bus.
    """
    return f"live:{tenant_id}:{route_id}"


class TripStartView(APIView):
    """POST /api/v1/transport/schedules/<id>/trips — begin a run."""

    permission_classes = [role_required("driver", "admin")]

    def post(self, request, schedule_id):
        # ``objects`` is tenant-scoped, so another tenant's schedule is simply
        # not found — no cross-tenant existence leak.
        try:
            schedule = BusSchedule.objects.get(pk=schedule_id)
        except BusSchedule.DoesNotExist:
            return fail("Schedule not found.", status=404)

        role = getattr(request.user, "role", None)
        if role != "admin" and str(schedule.driver_id) != str(request.user.id):
            return fail("You do not own this schedule.", status=403)

        if Trip.objects.filter(schedule=schedule, ended_at__isnull=True).exists():
            return fail("A trip is already active on this schedule.", status=400)

        trip = Trip.objects.create(
            tenant_id=get_current_tenant(),
            schedule=schedule,
            driver_id=request.user.id,
        )
        return ok(TripSerializer(trip).data, message="Trip started.", status=201)


class TripEndView(APIView):
    """POST /api/v1/transport/trips/<id>/end — finish a run."""

    permission_classes = [role_required("driver", "admin")]

    def post(self, request, pk):
        try:
            trip = Trip.objects.get(pk=pk)
        except Trip.DoesNotExist:
            return fail("Trip not found.", status=404)

        role = getattr(request.user, "role", None)
        if role != "admin" and str(trip.driver_id) != str(request.user.id):
            return fail("You do not own this trip.", status=403)

        if trip.ended_at is not None:
            return fail("Trip has already ended.", status=400)

        trip.ended_at = timezone.now()
        trip.save(update_fields=["ended_at"])
        # The run is over; drop the live dot rather than let it linger its TTL.
        cache.delete(_live_key(get_current_tenant(), trip.schedule.route_id))
        return ok(TripSerializer(trip).data, message="Trip ended.")


class BreadcrumbIngestView(APIView):
    """POST /api/v1/transport/trips/<id>/breadcrumbs — batched GPS samples.

    Batched rather than one-per-fix because the driver's app buffers points
    through tunnels and flushes them together. ``ignore_conflicts`` makes a
    replayed batch idempotent against the (trip, recorded_at) constraint.
    """

    permission_classes = [role_required("driver", "admin")]

    def post(self, request, pk):
        try:
            trip = Trip.objects.get(pk=pk)
        except Trip.DoesNotExist:
            return fail("Trip not found.", status=404)

        if str(trip.driver_id) != str(request.user.id):
            return fail("You do not own this trip.", status=403)

        serializer = BreadcrumbBatchSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid breadcrumb batch.", errors=serializer.errors, status=400)

        points = serializer.validated_data["points"]
        Breadcrumb.objects.bulk_create(
            [
                Breadcrumb(
                    tenant_id=get_current_tenant(),
                    trip=trip,
                    lat=point["lat"],
                    lng=point["lng"],
                    recorded_at=point["recorded_at"],
                )
                for point in points
            ],
            ignore_conflicts=True,
        )

        latest = max(points, key=lambda p: p["recorded_at"])
        cache.set(
            _live_key(get_current_tenant(), trip.schedule.route_id),
            {
                "lat": str(latest["lat"]),
                "lng": str(latest["lng"]),
                "recorded_at": latest["recorded_at"].isoformat(),
                "trip_id": str(trip.id),
            },
            timeout=LIVE_POSITION_TTL_SECONDS,
        )

        return ok({"accepted": len(points)}, message="Breadcrumbs recorded.", status=201)


class LivePositionView(APIView):
    """GET /api/v1/transport/routes/<id>/live — where the bus is right now.

    Served from Redis with a short TTL rather than from the Breadcrumb table:
    this is read by every student watching the route, and it is the one query
    that must not touch the DB on every poll.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, route_id):
        position = cache.get(_live_key(get_current_tenant(), route_id))
        if position is None:
            return fail("No bus is currently running on this route.", status=404)
        return ok(position)
