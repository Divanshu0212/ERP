"""GET /routes/{id}/seats returns which seats are gone, not just how many.

A bare available count cannot render a seat picker: the student would be able
to tap a seat that is already booked and only learn otherwise from the
uniqueness constraint. These tests cover the taken list and the departure time
that lets a student tell two buses on one route apart.
"""

import uuid

import pytest
from django.core.cache import cache
from transport.models import Booking
from transport.tests.test_seats_cache import _auth_client, _make_route_with_schedule

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_seats_lists_no_taken_seats_on_an_empty_bus():
    tenant_id = uuid.uuid4()
    route, _ = _make_route_with_schedule(tenant_id, capacity=4)

    response = _auth_client(tenant_id).get(f"/api/v1/transport/routes/{route.id}/seats")

    assert response.status_code == 200
    assert response.data["data"][0]["taken"] == []


def test_seats_reports_booked_seat_numbers_in_order():
    tenant_id = uuid.uuid4()
    route, schedule = _make_route_with_schedule(tenant_id, capacity=10)
    client = _auth_client(tenant_id)

    for seat_no in (3, 1):
        assert (
            client.post(
                "/api/v1/transport/bookings",
                {"schedule_id": str(schedule.id), "seat_no": seat_no},
                format="json",
            ).status_code
            == 201
        )

    response = client.get(f"/api/v1/transport/routes/{route.id}/seats")

    assert response.data["data"][0]["taken"] == [1, 3]


def test_a_cancelled_booking_frees_its_seat():
    tenant_id = uuid.uuid4()
    route, schedule = _make_route_with_schedule(tenant_id, capacity=5)
    client = _auth_client(tenant_id)

    client.post(
        "/api/v1/transport/bookings",
        {"schedule_id": str(schedule.id), "seat_no": 2},
        format="json",
    )
    Booking.all_objects.filter(schedule=schedule, seat_no=2).update(status="cancelled")

    response = client.get(f"/api/v1/transport/routes/{route.id}/seats")

    assert response.data["data"][0]["taken"] == []


def test_seats_carries_the_departure_time():
    tenant_id = uuid.uuid4()
    route, schedule = _make_route_with_schedule(tenant_id, capacity=2)

    response = _auth_client(tenant_id).get(f"/api/v1/transport/routes/{route.id}/seats")

    row = response.data["data"][0]
    assert row["departure_time"] == schedule.departure_time.isoformat()
