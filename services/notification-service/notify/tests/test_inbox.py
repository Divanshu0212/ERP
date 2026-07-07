"""Tests for Task 5.2: GET /api/v1/notify/inbox.

The inbox is doubly scoped: by tenant (via TenantMiddleware, so a token for a
different tenant sees nothing) AND by recipient user (the JWT ``sub`` claim, so
user A never sees user B's notifications even within the same tenant).

Tokens are minted directly with pyjwt rather than going through auth-service's
login flow — notification-service only ever *verifies* JWTs (see
suerp_common.auth.JWTAuthentication), so a token signed with the same HS256
``JWT_SIGNING_KEY`` and carrying the sub/role/tenant claims is
indistinguishable from one auth-service would have issued.
"""

import uuid

import jwt
import pytest
from django.conf import settings
from notify.models import Notification
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def _make_token(tenant_id, user_id, role="student"):
    claims = {
        "sub": str(user_id),
        "role": role,
        "tenant": str(tenant_id),
    }
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")


def _auth_client(tenant_id, user_id, **kwargs):
    client = APIClient()
    token = _make_token(tenant_id, user_id, **kwargs)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _make_notification(tenant_id, user_code, title="t", body="b", read=False):
    return Notification.all_objects.create(
        tenant_id=tenant_id,
        user_code=user_code,
        title=title,
        body=body,
        read=read,
    )


def test_inbox_returns_only_current_users_notifications_within_tenant():
    tenant_id = uuid.uuid4()
    user_a = "STU-100"
    user_b = "STU-200"

    _make_notification(tenant_id, user_a, title="for A #1")
    _make_notification(tenant_id, user_a, title="for A #2")
    _make_notification(tenant_id, user_b, title="for B")

    client = _auth_client(tenant_id, user_a)
    response = client.get("/api/v1/notify/inbox")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    # Standard paginated envelope.
    assert body["data"]["count"] == 2
    titles = {n["title"] for n in body["data"]["results"]}
    assert titles == {"for A #1", "for A #2"}
    assert "for B" not in titles


def test_inbox_orders_newest_first():
    tenant_id = uuid.uuid4()
    user_a = "STU-100"

    _make_notification(tenant_id, user_a, title="older")
    _make_notification(tenant_id, user_a, title="newer")

    client = _auth_client(tenant_id, user_a)
    response = client.get("/api/v1/notify/inbox")

    results = response.json()["data"]["results"]
    assert [n["title"] for n in results] == ["newer", "older"]


def test_inbox_is_tenant_scoped():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    user_a = "STU-100"

    _make_notification(tenant_a, user_a, title="tenant A note")

    # Same user id, but a token for a DIFFERENT tenant sees none of them.
    client_b = _auth_client(tenant_b, user_a)
    response = client_b.get("/api/v1/notify/inbox")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["count"] == 0
    assert body["data"]["results"] == []


def test_inbox_requires_authentication():
    response = APIClient().get("/api/v1/notify/inbox")
    assert response.status_code == 401


def test_mark_read_marks_only_current_users_notification():
    tenant_id = uuid.uuid4()
    user_a = "STU-100"
    user_b = "STU-200"

    note_a = _make_notification(tenant_id, user_a, title="A")
    note_b = _make_notification(tenant_id, user_b, title="B")

    client = _auth_client(tenant_id, user_a)

    # A can mark their own read.
    resp = client.post(f"/api/v1/notify/inbox/{note_a.id}/read")
    assert resp.status_code == 200
    note_a.refresh_from_db()
    assert note_a.read is True

    # A cannot mark B's notification read (404 — not visible to A).
    resp = client.post(f"/api/v1/notify/inbox/{note_b.id}/read")
    assert resp.status_code == 404
    note_b.refresh_from_db()
    assert note_b.read is False
