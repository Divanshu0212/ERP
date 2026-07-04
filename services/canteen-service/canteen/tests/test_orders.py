"""Tests for the canteen order flow: place, price-snapshot, list scoping,
status transitions, and role gating.

Tokens are minted directly with pyjwt — canteen-service only ever *verifies*
JWTs, so a token signed with the same HS256 JWT_SIGNING_KEY carrying
sub/role/tenant is indistinguishable from one auth-service would issue.
"""

import uuid

import jwt
import pytest
from canteen.models import MenuItem, Order, OrderItem
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

MENU_ENDPOINT = "/api/v1/menu-items/"
ORDERS_ENDPOINT = "/api/v1/orders/"


def _token(tenant_id, user_id=None, role="student"):
    return jwt.encode(
        {"sub": str(user_id or uuid.uuid4()), "role": role, "tenant": str(tenant_id)},
        settings.JWT_SIGNING_KEY,
        algorithm="HS256",
    )


def _client(tenant_id, **kwargs):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token(tenant_id, **kwargs)}")
    return client


def _menu_item(tenant_id, price="50.00", available=True, name="Meal"):
    return MenuItem.all_objects.create(
        tenant_id=tenant_id, name=name, price=price, available=available
    )


def test_student_places_order_snapshots_price_and_computes_total():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    item = _menu_item(tenant_id, price="40.00")

    resp = _client(tenant_id, user_id=student_id, role="student").post(
        ORDERS_ENDPOINT,
        {"items": [{"menu_item_id": str(item.id), "quantity": 3}]},
        format="json",
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "placed"
    assert body["data"]["total"] == "120.00"
    assert str(body["data"]["student_id"]) == str(student_id)
    assert len(body["data"]["items"]) == 1
    assert body["data"]["items"][0]["unit_price"] == "40.00"

    # A later price edit must NOT change the snapshot on the placed order.
    item.price = "999.00"
    item.save(update_fields=["price"])
    oi = OrderItem.all_objects.get(order_id=body["data"]["id"])
    assert str(oi.unit_price) == "40.00"


def test_order_with_unavailable_item_is_rejected():
    tenant_id = uuid.uuid4()
    item = _menu_item(tenant_id, available=False)

    resp = _client(tenant_id, role="student").post(
        ORDERS_ENDPOINT,
        {"items": [{"menu_item_id": str(item.id), "quantity": 1}]},
        format="json",
    )
    assert resp.status_code == 400
    assert Order.all_objects.count() == 0


def test_non_student_cannot_place_order():
    tenant_id = uuid.uuid4()
    item = _menu_item(tenant_id)
    resp = _client(tenant_id, role="canteen_owner").post(
        ORDERS_ENDPOINT,
        {"items": [{"menu_item_id": str(item.id), "quantity": 1}]},
        format="json",
    )
    assert resp.status_code == 403


def test_order_list_is_role_scoped():
    tenant_id = uuid.uuid4()
    student_a = uuid.uuid4()
    student_b = uuid.uuid4()
    Order.all_objects.create(tenant_id=tenant_id, student_id=student_a, total="10.00")
    Order.all_objects.create(tenant_id=tenant_id, student_id=student_b, total="20.00")

    # Student A sees only their own order.
    body = _client(tenant_id, user_id=student_a, role="student").get(ORDERS_ENDPOINT).json()
    assert body["data"]["count"] == 1
    assert str(body["data"]["results"][0]["student_id"]) == str(student_a)

    # Canteen owner sees the whole tenant queue.
    body = _client(tenant_id, role="canteen_owner").get(ORDERS_ENDPOINT).json()
    assert body["data"]["count"] == 2


def test_status_transition_valid_and_invalid():
    tenant_id = uuid.uuid4()
    order = Order.all_objects.create(
        tenant_id=tenant_id, student_id=uuid.uuid4(), total="10.00", status="placed"
    )
    owner = _client(tenant_id, role="canteen_owner")
    url = f"{ORDERS_ENDPOINT}{order.id}/status/"

    # placed -> preparing is legal.
    resp = owner.patch(url, {"status": "preparing"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "preparing"

    # preparing -> completed is illegal (must go through ready).
    resp = owner.patch(url, {"status": "completed"}, format="json")
    assert resp.status_code == 400


def test_student_cannot_change_status():
    tenant_id = uuid.uuid4()
    order = Order.all_objects.create(
        tenant_id=tenant_id, student_id=uuid.uuid4(), total="10.00", status="placed"
    )
    resp = _client(tenant_id, role="student").patch(
        f"{ORDERS_ENDPOINT}{order.id}/status/", {"status": "preparing"}, format="json"
    )
    assert resp.status_code == 403
