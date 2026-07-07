"""Transport domain models: Route, Stop, BusSchedule, Booking, Pass.

All five are ``suerp_common.tenancy.TenantModel`` subclasses — transport-service
is a normal resource service. ``objects`` is transparently scoped to the active
tenant; ``all_objects`` bypasses scoping for system operations (event consumers
that resolve tenant from the event payload, migrations, admin tooling).

``BusSchedule.driver_id``, ``Booking.student_user_code``, and
``Pass.student_user_code`` are bare opaque codes, not ForeignKeys:
auth-service/student-service owns those rows in its own database
(DB-per-service), so transport-service can only ever hold an opaque reference
to them (the user_code), never a real FK. ``Stop.route``/``BusSchedule.route``/
``Booking.schedule``/``Pass.route`` ARE real ForeignKeys since Route/BusSchedule
live in this same database.

Seat double-booking is prevented at the DB level by ``Booking``'s partial
UniqueConstraint on ``(tenant_id, schedule, seat_no)`` WHERE ``status=booked``:
a cancelled booking frees the seat, but two live ``booked`` rows for the same
seat on the same schedule can never coexist. The booking view relies on this
constraint (+ ``transaction.atomic``) to serialize concurrent bookings of the
same seat — see transport.views.BookingCreateView.
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class Route(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    start_point = models.CharField(max_length=255)
    end_point = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Stop(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="stops")
    name = models.CharField(max_length=255)
    sequence = models.PositiveSmallIntegerField()
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    def __str__(self):
        return f"{self.name} (#{self.sequence})"


class BusSchedule(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    route = models.ForeignKey(Route, on_delete=models.CASCADE, related_name="schedules")
    bus_no = models.CharField(max_length=50)
    # Reference to auth-service's User table (the driver), by user_code.
    driver_id = models.CharField(max_length=30)
    departure_time = models.DateTimeField()
    capacity = models.PositiveSmallIntegerField()

    def __str__(self):
        return f"{self.bus_no} @ {self.departure_time}"


class Booking(TenantModel):
    class Status(models.TextChoices):
        BOOKED = "booked", "Booked"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schedule = models.ForeignKey(BusSchedule, on_delete=models.CASCADE, related_name="bookings")
    # Reference to student-service's Student, by user_code.
    student_user_code = models.CharField(max_length=30)
    seat_no = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.BOOKED)
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # A seat can be held by at most one LIVE (booked) row per schedule.
            # Partial constraint so a cancelled booking frees the seat for
            # rebooking. This is the concurrency guard the booking flow leans
            # on to prevent double-booking under load.
            models.UniqueConstraint(
                fields=["tenant_id", "schedule", "seat_no"],
                condition=models.Q(status="booked"),
                name="booking_tenant_schedule_seat_booked_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant_id", "schedule"], name="booking_tenant_schedule"),
        ]

    def __str__(self):
        return f"Booking {self.id} seat {self.seat_no} ({self.status})"


class Pass(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student_user_code = models.CharField(max_length=30)
    route = models.ForeignKey(
        Route, on_delete=models.SET_NULL, related_name="passes", null=True, blank=True
    )
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Pass {self.id} (active={self.active})"
