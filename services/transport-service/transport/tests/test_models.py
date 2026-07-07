"""Model tests for Task 6.2: Route, Stop, BusSchedule, Booking, Pass.

All are suerp_common.tenancy.TenantModel subclasses — this proves tenant
isolation (objects vs all_objects) works, plus the seat double-booking guard:
the partial UniqueConstraint on (tenant_id, schedule, seat_no) WHERE
status=booked forbids two live bookings of the same seat on the same schedule.
"""

import uuid

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from suerp_common.tenancy import set_current_tenant
from transport.models import Booking, BusSchedule, Route

pytestmark = pytest.mark.django_db


def _make_route(tenant_id, name="Route A"):
    return Route.all_objects.create(
        tenant_id=tenant_id,
        name=name,
        start_point="Campus",
        end_point="Downtown",
    )


def _make_schedule(tenant_id, route=None, capacity=40, bus_no="BUS-1"):
    route = route or _make_route(tenant_id)
    return BusSchedule.all_objects.create(
        tenant_id=tenant_id,
        route=route,
        bus_no=bus_no,
        driver_id="DRV-001",
        departure_time=timezone.now(),
        capacity=capacity,
    )


def _make_booking(tenant_id, schedule, seat_no=1, status="booked", student_user_code=None):
    return Booking.all_objects.create(
        tenant_id=tenant_id,
        schedule=schedule,
        student_user_code=student_user_code or "STU-100",
        seat_no=seat_no,
        status=status,
    )


def test_duplicate_booked_seat_on_same_schedule_raises_integrity_error():
    tenant_id = uuid.uuid4()
    schedule = _make_schedule(tenant_id)
    _make_booking(tenant_id, schedule, seat_no=5, status="booked")

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            _make_booking(tenant_id, schedule, seat_no=5, status="booked")


def test_cancelled_seat_can_be_rebooked():
    """The partial constraint only forbids TWO live (booked) rows — a
    cancelled booking must not block rebooking that seat."""
    tenant_id = uuid.uuid4()
    schedule = _make_schedule(tenant_id)
    _make_booking(tenant_id, schedule, seat_no=7, status="cancelled")

    # Must not raise.
    rebooked = _make_booking(tenant_id, schedule, seat_no=7, status="booked")
    assert rebooked.status == "booked"


def test_same_seat_on_different_tenants_is_allowed():
    """Tenant-scoped uniqueness: the same schedule/seat under a different
    tenant_id is a distinct row (impossible in practice since schedules are
    tenant-owned, but proves the constraint is tenant-namespaced)."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    schedule = _make_schedule(tenant_a)
    _make_booking(tenant_a, schedule, seat_no=3, status="booked")
    # Different tenant_id -> constraint doesn't collide.
    other = _make_booking(tenant_b, schedule, seat_no=3, status="booked")
    assert other.tenant_id == tenant_b


def test_booking_tenant_scoping_isolates_by_tenant():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    schedule_a = _make_schedule(tenant_a)
    schedule_b = _make_schedule(tenant_b)

    booking_a = _make_booking(tenant_a, schedule_a, seat_no=1)
    booking_b = _make_booking(tenant_b, schedule_b, seat_no=1)

    try:
        set_current_tenant(str(tenant_a))
        scoped = list(Booking.objects.all())
        assert scoped == [booking_a]

        unscoped = set(Booking.all_objects.all())
        assert unscoped == {booking_a, booking_b}
    finally:
        set_current_tenant(None)


def test_booking_default_status_is_booked():
    tenant_id = uuid.uuid4()
    schedule = _make_schedule(tenant_id)
    booking = Booking.all_objects.create(
        tenant_id=tenant_id,
        schedule=schedule,
        student_user_code="STU-100",
        seat_no=2,
    )
    assert booking.status == "booked"
