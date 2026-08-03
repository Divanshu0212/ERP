"""Student-scoped allocation listing (hostel/views.py: MyAllocationsView).

The tenant-wide list in test_allocate.py answers a warden's question — "every
allocation in this institution". This file covers the student's question,
"where do I live", which must never leak the first answer.
"""

import uuid

import pytest

pytestmark = pytest.mark.django_db

from hostel.models import Allocation  # noqa: E402
from hostel.tests.test_allocate import _auth_client, _make_room  # noqa: E402


def _make_allocation(tenant_id, room, student_user_code, status="confirmed"):
    return Allocation.all_objects.create(
        tenant_id=tenant_id,
        room=room,
        student_user_code=student_user_code,
        status=status,
    )


def _results(response):
    data = response.json()["data"]
    return data["results"] if "results" in data else data


def test_student_sees_only_their_own_allocation():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=3, occupied_count=2, room_no="101")
    student_a = f"STU-{uuid.uuid4().hex[:8]}"
    student_b = f"STU-{uuid.uuid4().hex[:8]}"
    _make_allocation(tenant_id, room, student_a)
    _make_allocation(tenant_id, room, student_b)

    response = _auth_client(tenant_id, role="student", user_id=student_a).get(
        "/api/v1/hostel/allocations/mine"
    )

    assert response.status_code == 200, response.content
    items = _results(response)
    assert len(items) == 1
    assert items[0]["student_user_code"] == student_a


def test_allocations_from_another_tenant_are_invisible():
    tenant_id = uuid.uuid4()
    other_tenant = uuid.uuid4()
    student_user_code = f"STU-{uuid.uuid4().hex[:8]}"

    room = _make_room(tenant_id, room_no="101")
    other_room = _make_room(other_tenant, room_no="101")
    _make_allocation(tenant_id, room, student_user_code)
    # Same user code, different institution — must not bleed across.
    _make_allocation(other_tenant, other_room, student_user_code)

    response = _auth_client(tenant_id, role="student", user_id=student_user_code).get(
        "/api/v1/hostel/allocations/mine"
    )

    assert response.status_code == 200, response.content
    assert len(_results(response)) == 1


def test_student_with_no_allocation_gets_an_empty_list():
    tenant_id = uuid.uuid4()
    student_user_code = f"STU-{uuid.uuid4().hex[:8]}"

    response = _auth_client(tenant_id, role="student", user_id=student_user_code).get(
        "/api/v1/hostel/allocations/mine"
    )

    assert response.status_code == 200, response.content
    assert _results(response) == []


def test_warden_is_forbidden_from_the_student_route():
    tenant_id = uuid.uuid4()

    response = _auth_client(tenant_id, role="warden", user_id="WARD-1").get(
        "/api/v1/hostel/allocations/mine"
    )

    assert response.status_code == 403, response.content
