"""user.registered consumer — creates StudentProfile for role=student,
ignores every other role, and is idempotent under redelivery."""

import uuid

import pytest
from students.consumers import dispatch, handle_user_registered
from students.models import StudentProfile
from suerp_common.inbox import ProcessedEvent

pytestmark = pytest.mark.django_db


def _event(event_id=None, role="student", tenant_id=None, user_code="STU-1",
           department="CS", batch="2026", semester=2):
    return {
        "event_id": str(event_id or uuid.uuid4()),
        "type": "user.registered",
        "tenant_id": str(tenant_id or uuid.uuid4()),
        "payload": {
            "user_code": user_code,
            "role": role,
            "department": department,
            "batch": batch,
            "semester": semester,
        },
    }


def test_creates_student_profile_for_student_role():
    event = _event(role="student", user_code="STU-42", department="EE", batch="2027", semester=3)

    handle_user_registered(event)

    profile = StudentProfile.all_objects.get(tenant_id=event["tenant_id"], user_code="STU-42")
    assert profile.department == "EE"
    assert profile.batch == "2027"
    assert profile.semester == 3
    assert profile.cgpa == 0


def test_ignores_non_student_roles():
    event = _event(role="warden", user_code="WARD-1")

    handle_user_registered(event)

    assert not StudentProfile.all_objects.filter(user_code="WARD-1").exists()


def test_idempotent_on_replay_of_same_event_id():
    event = _event(event_id="11111111-1111-1111-1111-111111111111", user_code="STU-1")

    handle_user_registered(event)
    handle_user_registered(event)  # same event_id delivered twice

    assert StudentProfile.all_objects.filter(user_code="STU-1", tenant_id=event["tenant_id"]).count() == 1
    assert ProcessedEvent.objects.filter(event_id=event["event_id"]).count() == 1


def test_get_or_create_guards_against_distinct_event_ids_same_user_code():
    # Two genuinely different events (e.g. a raced double-publish) targeting
    # the same (tenant_id, user_code) must still yield exactly one profile.
    tenant_id = uuid.uuid4()
    event_1 = _event(tenant_id=tenant_id, user_code="STU-9")
    event_2 = _event(tenant_id=tenant_id, user_code="STU-9")

    handle_user_registered(event_1)
    handle_user_registered(event_2)

    assert StudentProfile.all_objects.filter(tenant_id=tenant_id, user_code="STU-9").count() == 1


def test_dispatch_routes_user_registered_to_handler():
    event = _event(user_code="STU-DISPATCH")

    dispatch(event)

    assert StudentProfile.all_objects.filter(user_code="STU-DISPATCH").exists()


def test_dispatch_ignores_unknown_event_type(caplog):
    event = _event(user_code="STU-UNKNOWN")
    event["type"] = "some.other.event"

    dispatch(event)  # must not raise

    assert not StudentProfile.all_objects.filter(user_code="STU-UNKNOWN").exists()
