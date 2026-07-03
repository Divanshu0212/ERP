"""Smoke test for exam-service (prototype/stub): auth + tenant isolation."""

import uuid

import jwt
import pytest
from django.conf import settings
from exams.models import ExamSchedule
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

ENDPOINT = "/api/v1/exams/"


def _token(tenant_id):
    return jwt.encode(
        {"sub": str(uuid.uuid4()), "role": "admin", "tenant": str(tenant_id)},
        settings.JWT_SIGNING_KEY,
        algorithm="HS256",
    )


def _auth_client(tenant_id):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token(tenant_id)}")
    return client


def test_list_requires_auth_and_returns_envelope():
    resp = _auth_client(uuid.uuid4()).get(ENDPOINT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["results"] == []


def test_list_is_tenant_scoped():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    ExamSchedule.all_objects.create(
        tenant_id=tenant_a,
        course_id=uuid.uuid4(),
        exam_date="2026-05-01",
        room_no="A-101",
        duration_minutes=180,
    )
    ExamSchedule.all_objects.create(
        tenant_id=tenant_b,
        course_id=uuid.uuid4(),
        exam_date="2026-05-01",
        room_no="B-202",
        duration_minutes=120,
    )

    body = _auth_client(tenant_a).get(ENDPOINT).json()
    assert body["data"]["count"] == 1
    assert body["data"]["results"][0]["room_no"] == "A-101"
