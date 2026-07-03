"""Smoke test for placement-service (prototype/stub): auth + tenant isolation."""

import uuid

import jwt
import pytest
from django.conf import settings
from placement.models import Drive
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

ENDPOINT = "/api/v1/drives/"


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
    Drive.all_objects.create(
        tenant_id=tenant_a,
        company_name="Acme A",
        job_title="SDE",
        ctc="1200000.00",
        eligibility="CGPA>7",
        drive_date="2026-08-01",
    )
    Drive.all_objects.create(
        tenant_id=tenant_b,
        company_name="Acme B",
        job_title="Analyst",
        ctc="900000.00",
        eligibility="CGPA>6",
        drive_date="2026-08-01",
    )

    body = _auth_client(tenant_a).get(ENDPOINT).json()
    assert body["data"]["count"] == 1
    assert body["data"]["results"][0]["company_name"] == "Acme A"
