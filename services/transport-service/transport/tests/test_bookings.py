"""Tests for Task 6.3: POST /api/v1/transport/bookings and GET /routes.

Double-booking the same seat is prevented by Booking's partial UniqueConstraint
(status=booked) inside one transaction.atomic(); idempotency_key retries return
the same booking; a schedule from another tenant isn't visible so tenant B
can't book on tenant A's bus.

Tokens are minted directly with pyjwt — transport-service only ever *verifies*
JWTs (suerp_common.auth.JWTAuthentication), so a token signed with the same
HS256 JWT_SIGNING_KEY carrying sub/role/tenant is indistinguishable from one
auth-service would issue.
"""

import uuid

import jwt
import pytest
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient
from transport.models import Booking, BusSchedule, Route

pytestmark = pytest.mark.django_db


def _make_token(tenant_id, user_id=None, role="student"):
    claims = {
        "sub": str(user_id or uuid.uuid4()),
        "role": role,
        "tenant": str(tenant_id),
    }
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")


def _auth_client(tenant_id, **kwargs):
    client = APIClient()
    token = _make_token(tenant_id, **kwargs)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _make_schedule(tenant_id, capacity=40, bus_no="BUS-1"):
    route = Route.all_objects.create(
        tenant_id=tenant_id, name="Route A", start_point="Campus", end_point="Downtown"
    )
    return BusSchedule.all_objects.create(
        tenant_id=tenant_id,
        route=route,
        bus_no=bus_no,
        driver_id=uuid.uuid4(),
        departure_time=timezone.now(),
        capacity=capacity,
    )


def test_booking_available_seat_returns_201_and_creates_one_booking():
    tenant_id = uuid.uuid4()
    schedule = _make_schedule(tenant_id)
    student_id = uuid.uuid4()
    client = _auth_client(tenant_id)

    response = client.post(
        "/api/v1/transport/bookings",
        {"schedule_id": str(schedule.id), "seat_no": 5, "student_id": str(student_id)},
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["seat_no"] == 5
    assert body["data"]["status"] == "booked"
    assert body["data"]["schedule_id"] == str(schedule.id)

    bookings = Booking.all_objects.filter(schedule=schedule, status="booked")
    assert bookings.count() == 1


def test_double_booking_same_seat_returns_400():
    tenant_id = uuid.uuid4()
    schedule = _make_schedule(tenant_id)
    client = _auth_client(tenant_id)

    first = client.post(
        "/api/v1/transport/bookings",
        {"schedule_id": str(schedule.id), "seat_no": 9},
        format="json",
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/transport/bookings",
        {"schedule_id": str(schedule.id), "seat_no": 9},
        format="json",
    )
    assert second.status_code == 400
    body = second.json()
    assert body["success"] is False
    assert "taken" in body["message"].lower()

    assert Booking.all_objects.filter(schedule=schedule, seat_no=9, status="booked").count() == 1


def test_idempotency_key_returns_same_booking_and_creates_one():
    tenant_id = uuid.uuid4()
    schedule = _make_schedule(tenant_id)
    client = _auth_client(tenant_id)
    key = "idem-123"

    first = client.post(
        "/api/v1/transport/bookings",
        {"schedule_id": str(schedule.id), "seat_no": 11, "idempotency_key": key},
        format="json",
    )
    assert first.status_code == 201
    booking_id = first.json()["data"]["id"]

    second = client.post(
        "/api/v1/transport/bookings",
        {"schedule_id": str(schedule.id), "seat_no": 11, "idempotency_key": key},
        format="json",
    )
    assert second.status_code == 200
    assert second.json()["data"]["id"] == booking_id

    assert Booking.all_objects.filter(schedule=schedule, idempotency_key=key).count() == 1


def test_tenant_b_cannot_book_on_tenant_a_schedule():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    schedule = _make_schedule(tenant_a)
    client_b = _auth_client(tenant_b)

    response = client_b.post(
        "/api/v1/transport/bookings",
        {"schedule_id": str(schedule.id), "seat_no": 1},
        format="json",
    )

    assert response.status_code == 404
    assert Booking.all_objects.filter(schedule=schedule).count() == 0


def test_booking_derives_student_from_jwt_sub_when_omitted():
    tenant_id = uuid.uuid4()
    schedule = _make_schedule(tenant_id)
    student_id = uuid.uuid4()
    client = _auth_client(tenant_id, user_id=student_id)

    response = client.post(
        "/api/v1/transport/bookings",
        {"schedule_id": str(schedule.id), "seat_no": 4},
        format="json",
    )

    assert response.status_code == 201
    booking = Booking.all_objects.get(id=response.json()["data"]["id"])
    assert str(booking.student_id) == str(student_id)


def test_routes_list_is_tenant_scoped_and_paginated():
    tenant_id = uuid.uuid4()
    other_tenant = uuid.uuid4()
    Route.all_objects.create(tenant_id=tenant_id, name="Mine", start_point="A", end_point="B")
    Route.all_objects.create(tenant_id=other_tenant, name="Theirs", start_point="C", end_point="D")

    client = _auth_client(tenant_id)
    response = client.get("/api/v1/transport/routes")

    assert response.status_code == 200
    results = response.data["data"]["results"]
    names = {r["name"] for r in results}
    assert names == {"Mine"}
