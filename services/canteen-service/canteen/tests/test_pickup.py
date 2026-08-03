"""Pickup tokens: the handoff, not a button, completes an order.

Tokens are minted directly with pyjwt, following test_orders.py — this
service only ever *verifies* JWTs.
"""

import uuid

import jwt
import pytest
from canteen.models import MenuItem, Order, OrderItem
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

TENANT_A = uuid.uuid4()


def _client(tenant_id, role="student", sub="STU-001"):
    token = jwt.encode(
        {"sub": str(sub), "role": role, "tenant": str(tenant_id)},
        settings.JWT_SIGNING_KEY,
        algorithm="HS256",
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _order(tenant_id, status="ready", student="STU-001"):
    item = MenuItem.all_objects.create(
        tenant_id=tenant_id, name="Chai", price="15.00", available=True
    )
    order = Order.all_objects.create(
        tenant_id=tenant_id, student_user_code=student, status=status, total="15.00"
    )
    OrderItem.all_objects.create(
        tenant_id=tenant_id, order=order, menu_item=item, quantity=1, unit_price="15.00"
    )
    return order


def test_a_ready_order_mints_a_pickup_token():
    order = _order(TENANT_A)

    response = _client(TENANT_A).get(f"/api/v1/orders/{order.id}/pickup-token")

    assert response.status_code == 200
    assert response.json()["data"]["token"]


def test_an_order_that_is_not_ready_has_no_token():
    order = _order(TENANT_A, status="preparing")

    response = _client(TENANT_A).get(f"/api/v1/orders/{order.id}/pickup-token")

    assert response.status_code == 400


def test_another_student_cannot_mint_a_token_for_your_order():
    order = _order(TENANT_A, student="STU-001")

    response = _client(TENANT_A, sub="STU-002").get(f"/api/v1/orders/{order.id}/pickup-token")

    assert response.status_code == 403


def test_scanning_a_pickup_token_completes_the_order():
    order = _order(TENANT_A)
    token = _client(TENANT_A).get(f"/api/v1/orders/{order.id}/pickup-token").json()["data"]["token"]

    owner = _client(TENANT_A, role="canteen_owner", sub="OWN-001")
    response = owner.post("/api/v1/orders/pickup", {"token": token}, format="json")

    assert response.status_code == 200
    order.refresh_from_db()
    assert order.status == "completed"


def test_the_same_pickup_token_cannot_complete_twice():
    order = _order(TENANT_A)
    token = _client(TENANT_A).get(f"/api/v1/orders/{order.id}/pickup-token").json()["data"]["token"]
    owner = _client(TENANT_A, role="canteen_owner", sub="OWN-001")
    owner.post("/api/v1/orders/pickup", {"token": token}, format="json")

    response = owner.post("/api/v1/orders/pickup", {"token": token}, format="json")

    assert response.status_code == 400


def test_students_cannot_complete_their_own_order():
    order = _order(TENANT_A)
    token = _client(TENANT_A).get(f"/api/v1/orders/{order.id}/pickup-token").json()["data"]["token"]

    response = _client(TENANT_A).post("/api/v1/orders/pickup", {"token": token}, format="json")

    assert response.status_code == 403


def test_a_pickup_token_from_another_tenant_is_rejected():
    """A signed token is still scoped to the institution that minted it."""
    order = _order(TENANT_A)
    token = _client(TENANT_A).get(f"/api/v1/orders/{order.id}/pickup-token").json()["data"]["token"]

    other_owner = _client(uuid.uuid4(), role="canteen_owner", sub="OWN-002")
    response = other_owner.post("/api/v1/orders/pickup", {"token": token}, format="json")

    assert response.status_code == 400
    order.refresh_from_db()
    assert order.status == "ready"
