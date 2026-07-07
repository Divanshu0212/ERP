"""Tests for the additive Razorpay payment flow on canteen-service.

Covers the checkout endpoint's server-side total (simulated mode, no keys) and
order creation with Razorpay proof (verified/rejected). The order-create path
without razorpay fields is already covered by test_orders.py and must keep
working — that is the whole point of the simulated fallback.

``suerp_common.razorpay_gateway`` is monkeypatched, so no network calls to
Razorpay happen in tests.
"""

import uuid

import jwt
import pytest
from canteen.models import MenuItem, Order
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

CHECKOUT_ENDPOINT = "/api/v1/orders/checkout"
ORDERS_ENDPOINT = "/api/v1/orders/"


def _token(tenant_id, user_id=None, role="student"):
    return jwt.encode(
        {"sub": user_id or f"STU{uuid.uuid4().hex[:27]}", "role": role, "tenant": str(tenant_id)},
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


def test_checkout_computes_total_and_returns_sim_order_when_unconfigured(monkeypatch):
    from canteen import views

    monkeypatch.setattr(views.razorpay_gateway, "is_configured", lambda: False)
    tenant_id = uuid.uuid4()
    item = _menu_item(tenant_id, price="40.00")

    resp = _client(tenant_id, role="student").post(
        CHECKOUT_ENDPOINT,
        {"items": [{"menu_item_id": str(item.id), "quantity": 3}]},
        format="json",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["amount"] == "120.00"
    assert data["currency"] == "INR"
    assert data["order_id"].startswith("SIM-")
    assert data["key_id"] == ""
    # No order rows created by checkout.
    assert Order.all_objects.count() == 0


def test_checkout_uses_real_gateway_when_configured(monkeypatch):
    from canteen import views

    monkeypatch.setattr(views.razorpay_gateway, "is_configured", lambda: True)
    monkeypatch.setattr(
        views.razorpay_gateway,
        "create_order",
        lambda amount, receipt: {
            "order_id": "order_RZP1",
            "amount": str(amount),
            "currency": "INR",
            "key_id": "test_key_id",
        },
    )
    tenant_id = uuid.uuid4()
    item = _menu_item(tenant_id, price="25.00")

    resp = _client(tenant_id, role="student").post(
        CHECKOUT_ENDPOINT,
        {"items": [{"menu_item_id": str(item.id), "quantity": 2}]},
        format="json",
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["order_id"] == "order_RZP1"
    assert data["amount"] == "50.00"


def test_checkout_is_student_only():
    tenant_id = uuid.uuid4()
    item = _menu_item(tenant_id)
    resp = _client(tenant_id, role="canteen_owner").post(
        CHECKOUT_ENDPOINT,
        {"items": [{"menu_item_id": str(item.id), "quantity": 1}]},
        format="json",
    )
    assert resp.status_code == 403


def test_order_create_with_valid_signature_stores_gateway_ref(monkeypatch):
    from canteen import views

    monkeypatch.setattr(views.razorpay_gateway, "is_configured", lambda: True)
    monkeypatch.setattr(views.razorpay_gateway, "verify_signature", lambda *a: True)
    tenant_id = uuid.uuid4()
    item = _menu_item(tenant_id, price="30.00")

    resp = _client(tenant_id, role="student").post(
        ORDERS_ENDPOINT,
        {
            "items": [{"menu_item_id": str(item.id), "quantity": 2}],
            "razorpay_order_id": "order_RZP1",
            "razorpay_payment_id": "pay_RZP2",
            "razorpay_signature": "sig_RZP3",
        },
        format="json",
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["total"] == "60.00"
    order = Order.all_objects.get(id=resp.json()["data"]["id"])
    assert order.gateway_ref == "pay_RZP2"


def test_order_create_with_invalid_signature_is_rejected(monkeypatch):
    from canteen import views

    monkeypatch.setattr(views.razorpay_gateway, "is_configured", lambda: True)
    monkeypatch.setattr(views.razorpay_gateway, "verify_signature", lambda *a: False)
    tenant_id = uuid.uuid4()
    item = _menu_item(tenant_id, price="30.00")

    resp = _client(tenant_id, role="student").post(
        ORDERS_ENDPOINT,
        {
            "items": [{"menu_item_id": str(item.id), "quantity": 2}],
            "razorpay_order_id": "order_RZP1",
            "razorpay_payment_id": "pay_RZP2",
            "razorpay_signature": "sig_BAD",
        },
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["success"] is False
    assert Order.all_objects.count() == 0
