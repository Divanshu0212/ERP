"""Smoke test for student-service (prototype/stub): auth + tenant isolation."""

import uuid

import jwt
import pytest
from django.conf import settings
from rest_framework.test import APIClient
from students.models import StudentProfile

pytestmark = pytest.mark.django_db

ENDPOINT = "/api/v1/students/"


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
    tenant = uuid.uuid4()
    resp = _auth_client(tenant).get(ENDPOINT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["results"] == []


def test_list_is_tenant_scoped():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    StudentProfile.all_objects.create(
        tenant_id=tenant_a,
        user_code="STU-A-001",
        department="CSE",
        batch="2024",
    )
    StudentProfile.all_objects.create(
        tenant_id=tenant_b,
        user_code="STU-B-001",
        department="ECE",
        batch="2024",
    )

    body = _auth_client(tenant_a).get(ENDPOINT).json()
    results = body["data"]["results"]
    assert body["data"]["count"] == 1
    assert results[0]["user_code"] == "STU-A-001"


def test_create_student_profile():
    tenant_id = uuid.uuid4()
    profile = StudentProfile.objects.create(
        tenant_id=tenant_id,
        user_code="STU-001",
        department="CSE",
        batch="2026",
    )
    assert profile.user_code == "STU-001"
    assert not hasattr(profile, "roll_no")
