"""Geofenced attendance: session, rolling code, and proxy resistance.

Tokens follow this service's existing convention (see test_smoke.py):
pyjwt-minted bearer tokens, ``all_objects`` for setup rows.
"""

import uuid

import jwt
import pytest
from attendance.models import AttendanceMark
from attendance.rolling_code import current_code
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()

# A classroom and a point ~400 m away, well outside any sane radius.
ROOM = {"lat": "12.971599", "lng": "77.594566"}
FAR_AWAY = {"lat": "12.975200", "lng": "77.594566"}


def _client(tenant_id, role="student", sub="STU-001"):
    token = jwt.encode(
        {"sub": str(sub), "role": role, "tenant": str(tenant_id)},
        settings.JWT_SIGNING_KEY,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _open_session(tenant_id, faculty="FAC-001"):
    client = _client(tenant_id, role="faculty", sub=faculty)
    return client.post(
        "/api/v1/attendance/sessions",
        {"course_code": "CS101", **ROOM, "radius_m": 50},
        format="json",
    ).json()["data"]


def _mark(client, session_id, code, position=ROOM, mock_location=False):
    return client.post(
        f"/api/v1/attendance/sessions/{session_id}/mark",
        {**position, "code": code, "mock_location": mock_location},
        format="json",
    )


def test_faculty_opens_a_session_and_gets_the_geofence():
    session = _open_session(TENANT_A)

    assert session["radius_m"] == 50
    assert session["closed_at"] is None


def test_students_cannot_open_a_session():
    client = _client(TENANT_A)

    response = client.post(
        "/api/v1/attendance/sessions",
        {"course_code": "CS101", **ROOM, "radius_m": 50},
        format="json",
    )

    assert response.status_code == 403


def test_a_student_inside_the_geofence_with_the_current_code_is_marked():
    session = _open_session(TENANT_A)
    code = current_code(session["id"])

    response = _mark(_client(TENANT_A), session["id"], code)

    assert response.status_code == 201
    assert AttendanceMark.all_objects.count() == 1


def test_a_student_outside_the_geofence_is_refused():
    session = _open_session(TENANT_A)
    code = current_code(session["id"])

    response = _mark(_client(TENANT_A), session["id"], code, position=FAR_AWAY)

    assert response.status_code == 400
    assert AttendanceMark.all_objects.count() == 0


def test_a_stale_code_is_refused():
    """The whole point: being in the room is not enough without the code."""
    session = _open_session(TENANT_A)

    response = _mark(_client(TENANT_A), session["id"], "000000")

    assert response.status_code == 400
    assert AttendanceMark.all_objects.count() == 0


def test_a_student_cannot_mark_twice():
    session = _open_session(TENANT_A)
    code = current_code(session["id"])
    client = _client(TENANT_A)
    _mark(client, session["id"], code)

    response = _mark(client, session["id"], code)

    assert response.status_code == 409
    assert AttendanceMark.all_objects.count() == 1


def test_a_mock_location_report_is_recorded_but_refused():
    session = _open_session(TENANT_A)
    code = current_code(session["id"])

    response = _mark(_client(TENANT_A), session["id"], code, mock_location=True)

    assert response.status_code == 400


def test_marking_a_closed_session_is_refused():
    session = _open_session(TENANT_A)
    faculty = _client(TENANT_A, role="faculty", sub="FAC-001")
    faculty.post(f"/api/v1/attendance/sessions/{session['id']}/close", format="json")
    code = current_code(session["id"])

    response = _mark(_client(TENANT_A), session["id"], code)

    assert response.status_code == 400


def test_sessions_do_not_leak_across_tenants():
    session = _open_session(TENANT_A)
    code = current_code(session["id"])

    response = _mark(_client(TENANT_B, sub="STU-999"), session["id"], code)

    assert response.status_code == 404


def test_the_summary_reports_a_percentage_per_course():
    session = _open_session(TENANT_A)
    _mark(_client(TENANT_A), session["id"], current_code(session["id"]))
    # A second meeting the student misses, so the percentage is not a
    # trivially-100% number that would pass with a broken denominator.
    _open_session(TENANT_A)

    response = _client(TENANT_A).get("/api/v1/attendance/summary")

    assert response.status_code == 200
    row = response.json()["data"][0]
    assert row["course_code"] == "CS101"
    assert row["held"] == 2
    assert row["attended"] == 1
    assert row["percentage"] == 50.0
