"""Smoke test for analytics-service (prototype/stub): auth + tenant isolation."""

import uuid

import jwt
import pytest
from analytics.models import MetricSnapshot
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

ENDPOINT = "/api/v1/metrics/"


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
    MetricSnapshot.all_objects.create(tenant_id=tenant_a, metric="active_users", value=42.0)
    MetricSnapshot.all_objects.create(tenant_id=tenant_b, metric="active_users", value=99.0)

    body = _auth_client(tenant_a).get(ENDPOINT).json()
    assert body["data"]["count"] == 1
    assert body["data"]["results"][0]["value"] == 42.0
