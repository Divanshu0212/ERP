"""Smoke test for canteen-service (prototype/stub): auth + tenant isolation."""

import uuid

import jwt
import pytest
from canteen.models import MenuItem
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

ENDPOINT = "/api/v1/menu-items/"


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
    MenuItem.all_objects.create(tenant_id=tenant_a, name="Tenant A Meal", price="50.00")
    MenuItem.all_objects.create(tenant_id=tenant_b, name="Tenant B Meal", price="60.00")

    body = _auth_client(tenant_a).get(ENDPOINT).json()
    assert body["data"]["count"] == 1
    assert body["data"]["results"][0]["name"] == "Tenant A Meal"
