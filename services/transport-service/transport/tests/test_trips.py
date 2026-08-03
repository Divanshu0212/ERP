"""Driver trip lifecycle and GPS breadcrumb ingest.

Tokens and fixtures follow this service's existing convention (see
test_schedules.py): pyjwt-minted tokens and ``all_objects`` for setup rows,
since no tenant is active outside a request.
"""

import uuid

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from transport.models import Breadcrumb, BusSchedule, Route, Trip
from transport.tests.test_schedules import _token

pytestmark = pytest.mark.django_db

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _client(tenant_id, role="driver", sub="DRV-001"):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token(tenant_id, user_id=sub, role=role)}")
    return client


def _schedule(tenant_id, driver_id="DRV-001"):
    route = Route.all_objects.create(
        tenant_id=tenant_id, name="North Loop", start_point="Gate", end_point="Campus"
    )
    return BusSchedule.all_objects.create(
        tenant_id=tenant_id,
        route=route,
        bus_no="KA-01-1234",
        driver_id=driver_id,
        departure_time="2026-08-04T08:00:00Z",
        capacity=40,
    )


def test_driver_starts_a_trip_on_their_own_schedule():
    schedule = _schedule(TENANT_A)
    client = _client(TENANT_A)

    response = client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json")

    assert response.status_code == 201, response.content
    assert response.json()["data"]["ended_at"] is None
    assert Trip.all_objects.count() == 1


def test_driver_cannot_start_a_trip_on_someone_elses_schedule():
    schedule = _schedule(TENANT_A, driver_id="DRV-999")
    client = _client(TENANT_A)

    response = client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json")

    assert response.status_code == 403


def test_starting_a_second_trip_while_one_is_active_is_rejected():
    schedule = _schedule(TENANT_A)
    client = _client(TENANT_A)
    client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json")

    response = client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json")

    assert response.status_code == 400


def test_ending_a_trip_stamps_the_end_time():
    schedule = _schedule(TENANT_A)
    client = _client(TENANT_A)
    trip = client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json").json()[
        "data"
    ]

    response = client.post(f"/api/v1/transport/trips/{trip['id']}/end", format="json")

    assert response.status_code == 200, response.content
    assert response.json()["data"]["ended_at"] is not None


def test_breadcrumb_batch_is_stored():
    schedule = _schedule(TENANT_A)
    client = _client(TENANT_A)
    trip = client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json").json()[
        "data"
    ]

    response = client.post(
        f"/api/v1/transport/trips/{trip['id']}/breadcrumbs",
        {
            "points": [
                {"lat": "12.971599", "lng": "77.594566", "recorded_at": "2026-08-04T08:01:00Z"},
                {"lat": "12.972000", "lng": "77.595000", "recorded_at": "2026-08-04T08:01:15Z"},
            ]
        },
        format="json",
    )

    assert response.status_code == 201, response.content
    assert Breadcrumb.all_objects.filter(trip_id=trip["id"]).count() == 2


def test_replaying_the_same_breadcrumb_batch_does_not_duplicate():
    schedule = _schedule(TENANT_A)
    client = _client(TENANT_A)
    trip = client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json").json()[
        "data"
    ]
    body = {
        "points": [{"lat": "12.971599", "lng": "77.594566", "recorded_at": "2026-08-04T08:01:00Z"}]
    }

    client.post(f"/api/v1/transport/trips/{trip['id']}/breadcrumbs", body, format="json")
    client.post(f"/api/v1/transport/trips/{trip['id']}/breadcrumbs", body, format="json")

    assert Breadcrumb.all_objects.filter(trip_id=trip["id"]).count() == 1


def test_students_can_read_the_live_position():
    schedule = _schedule(TENANT_A)
    driver = _client(TENANT_A)
    trip = driver.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json").json()[
        "data"
    ]
    driver.post(
        f"/api/v1/transport/trips/{trip['id']}/breadcrumbs",
        {
            "points": [
                {"lat": "12.971599", "lng": "77.594566", "recorded_at": "2026-08-04T08:01:00Z"}
            ]
        },
        format="json",
    )

    student = _client(TENANT_A, role="student", sub="STU-001")
    response = student.get(f"/api/v1/transport/routes/{schedule.route_id}/live")

    assert response.status_code == 200, response.content
    assert response.json()["data"]["lat"] == "12.971599"


def test_live_position_does_not_leak_across_tenants():
    schedule = _schedule(TENANT_A)
    driver = _client(TENANT_A)
    trip = driver.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json").json()[
        "data"
    ]
    driver.post(
        f"/api/v1/transport/trips/{trip['id']}/breadcrumbs",
        {
            "points": [
                {"lat": "12.971599", "lng": "77.594566", "recorded_at": "2026-08-04T08:01:00Z"}
            ]
        },
        format="json",
    )

    other = _client(TENANT_B, role="student", sub="STU-002")
    response = other.get(f"/api/v1/transport/routes/{schedule.route_id}/live")

    assert response.status_code == 404
