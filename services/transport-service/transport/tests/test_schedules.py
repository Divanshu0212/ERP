"""Tests for the driver schedule endpoints: /schedules/mine and
/schedules/<id>/bookings, including role scoping and ownership enforcement.
"""

import uuid

import jwt
import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient
from transport.models import Booking, BusSchedule, Route

pytestmark = pytest.mark.django_db


def _token(tenant_id, user_id=None, role="driver"):
    return jwt.encode(
        {"sub": str(user_id or uuid.uuid4()), "role": role, "tenant": str(tenant_id)},
        settings.JWT_SIGNING_KEY,
        algorithm="HS256",
    )


def _client(tenant_id, **kwargs):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token(tenant_id, **kwargs)}")
    return client


def _schedule(tenant_id, driver_id, bus_no="BUS-1", capacity=40):
    route = Route.all_objects.create(
        tenant_id=tenant_id, name="Route A", start_point="Campus", end_point="Downtown"
    )
    return BusSchedule.all_objects.create(
        tenant_id=tenant_id,
        route=route,
        bus_no=bus_no,
        driver_id=driver_id,
        departure_time=timezone.now(),
        capacity=capacity,
    )


def test_driver_sees_only_own_schedules_with_booked_count():
    tenant_id = uuid.uuid4()
    driver_id = "DRV-001"
    other_driver = "DRV-002"
    mine = _schedule(tenant_id, driver_id, bus_no="MINE")
    _schedule(tenant_id, other_driver, bus_no="THEIRS")
    Booking.all_objects.create(
        tenant_id=tenant_id,
        schedule=mine,
        student_user_code="STU-100",
        seat_no=1,
        status="booked",
    )

    resp = _client(tenant_id, user_id=driver_id, role="driver").get(
        "/api/v1/transport/schedules/mine"
    )
    assert resp.status_code == 200
    results = resp.json()["data"]["results"]
    assert len(results) == 1
    assert results[0]["bus_no"] == "MINE"
    assert results[0]["booked_count"] == 1
    assert results[0]["route"]["name"] == "Route A"


def test_admin_sees_all_tenant_schedules():
    tenant_id = uuid.uuid4()
    _schedule(tenant_id, "DRV-001", bus_no="A")
    _schedule(tenant_id, "DRV-002", bus_no="B")

    resp = _client(tenant_id, role="admin").get("/api/v1/transport/schedules/mine")
    assert resp.status_code == 200
    assert resp.json()["data"]["count"] == 2


def test_student_forbidden_from_driver_schedules():
    tenant_id = uuid.uuid4()
    resp = _client(tenant_id, role="student").get("/api/v1/transport/schedules/mine")
    assert resp.status_code == 403


def test_schedule_bookings_ownership_enforced():
    tenant_id = uuid.uuid4()
    driver_id = "DRV-001"
    schedule = _schedule(tenant_id, driver_id)
    Booking.all_objects.create(
        tenant_id=tenant_id,
        schedule=schedule,
        student_user_code="STU-100",
        seat_no=3,
        status="booked",
    )

    # Owning driver can read the bookings.
    resp = _client(tenant_id, user_id=driver_id, role="driver").get(
        f"/api/v1/transport/schedules/{schedule.id}/bookings"
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["count"] == 1

    # A different driver is forbidden.
    resp = _client(tenant_id, user_id="DRV-999", role="driver").get(
        f"/api/v1/transport/schedules/{schedule.id}/bookings"
    )
    assert resp.status_code == 403

    # Admin can read any schedule's bookings.
    resp = _client(tenant_id, role="admin").get(
        f"/api/v1/transport/schedules/{schedule.id}/bookings"
    )
    assert resp.status_code == 200
