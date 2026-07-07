"""Tests for Task 6.3 seat-availability caching (GET /routes/{id}/seats).

Available = capacity - count(booked). The count is cached in Django's cache
(LocMemCache under test settings — no live Redis needed) under a tenant-
namespaced key with a short TTL, and invalidated on a successful booking so the
next read recomputes. These tests assert the numeric availability and that a
booking is reflected on the next read.
"""

import uuid

import jwt
import pytest
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient
from transport.models import BusSchedule, Route

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _make_token(tenant_id, user_id=None, role="student"):
    claims = {"sub": user_id or f"STU-{uuid.uuid4().hex[:8]}", "role": role, "tenant": str(tenant_id)}
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")


def _auth_client(tenant_id, **kwargs):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_make_token(tenant_id, **kwargs)}")
    return client


def _make_route_with_schedule(tenant_id, capacity=3):
    route = Route.all_objects.create(
        tenant_id=tenant_id, name="Route A", start_point="Campus", end_point="Downtown"
    )
    schedule = BusSchedule.all_objects.create(
        tenant_id=tenant_id,
        route=route,
        bus_no="BUS-1",
        driver_id="DRV-001",
        departure_time=timezone.now(),
        capacity=capacity,
    )
    return route, schedule


def test_seats_reflects_capacity_minus_booked():
    tenant_id = uuid.uuid4()
    route, schedule = _make_route_with_schedule(tenant_id, capacity=3)
    client = _auth_client(tenant_id)

    response = client.get(f"/api/v1/transport/routes/{route.id}/seats")
    assert response.status_code == 200
    rows = response.data["data"]
    assert len(rows) == 1
    row = rows[0]
    assert row["schedule_id"] == str(schedule.id)
    assert row["capacity"] == 3
    assert row["available"] == 3


def test_seats_decrements_after_booking_cache_invalidated():
    tenant_id = uuid.uuid4()
    route, schedule = _make_route_with_schedule(tenant_id, capacity=3)
    client = _auth_client(tenant_id)

    # Warm the cache: 3 available.
    first = client.get(f"/api/v1/transport/routes/{route.id}/seats")
    assert first.data["data"][0]["available"] == 3

    # Book one seat -> the view invalidates the cache key.
    booking = client.post(
        "/api/v1/transport/bookings",
        {"schedule_id": str(schedule.id), "seat_no": 1},
        format="json",
    )
    assert booking.status_code == 201

    # Next read recomputes: one fewer seat.
    second = client.get(f"/api/v1/transport/routes/{route.id}/seats")
    assert second.data["data"][0]["available"] == 2
