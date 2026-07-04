"""Canteen endpoints: menu items (browse/manage) and orders (place/track/fulfil).

Permission model:
  - Menu browse (GET) is open to any authenticated user (students need to see
    the menu); menu mutations (POST/PATCH) are canteen_owner/admin only.
  - Placing an order (POST /orders/) is student-only.
  - Listing orders (GET /orders/) is role-scoped: students see only their own
    orders, canteen_owner/admin see the whole tenant queue. Both sides are
    capped to a 30-day retention window.
  - Advancing an order's status (PATCH /orders/<id>/status/) is
    canteen_owner/admin only and only along legal forward transitions.

Order creation snapshots ``MenuItem.price`` into ``OrderItem.unit_price`` and
computes the total server-side inside one ``transaction.atomic()`` — any
client-sent price is ignored, and menu items must belong to the caller's tenant
and be ``available=True`` or the whole order is rejected 400.
"""

import uuid
from datetime import timedelta

from canteen.models import MenuItem, Order, OrderItem
from canteen.serializers import (
    CheckoutSerializer,
    MenuItemSerializer,
    OrderCreateSerializer,
    OrderSerializer,
)
from django.db import transaction
from django.utils import timezone
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from suerp_common import razorpay_gateway
from suerp_common.envelope import fail, ok
from suerp_common.permissions import role_required

# Roles allowed to manage the menu and the order queue.
_STAFF_ROLES = ("canteen_owner", "admin")

# Orders are visible/queryable for 30 days after creation (both sides).
ORDER_RETENTION_DAYS = 30

# Legal forward status transitions for an order.
_ALLOWED_TRANSITIONS = {
    Order.Status.PLACED: {Order.Status.PREPARING, Order.Status.CANCELLED},
    Order.Status.PREPARING: {Order.Status.READY, Order.Status.CANCELLED},
    Order.Status.READY: {Order.Status.COMPLETED},
    Order.Status.COMPLETED: set(),
    Order.Status.CANCELLED: set(),
}


class _CartError(Exception):
    """Raised by ``_resolve_cart`` carrying the 400 response to return."""

    def __init__(self, response):
        self.response = response


def _resolve_cart(items):
    """Validate and price a cart's line items server-side.

    Shared by checkout (prices only) and order creation (prices, then builds
    the order). Collapses duplicate ``menu_item_id`` lines, verifies every item
    exists in the caller's tenant and is ``available``, and returns
    ``(wanted, menu_items, total)``. Raises ``_CartError`` with a 400 response
    on any missing/unavailable item. Any client-sent price is ignored.
    """
    wanted = {}
    for line in items:
        wanted[line["menu_item_id"]] = wanted.get(line["menu_item_id"], 0) + line["quantity"]

    # ``objects`` is tenant-scoped, so cross-tenant ids simply aren't found
    # here — no cross-tenant leak.
    menu_items = {mi.id: mi for mi in MenuItem.objects.filter(id__in=list(wanted.keys()))}

    missing = [str(mid) for mid in wanted if mid not in menu_items]
    if missing:
        raise _CartError(
            fail("Some menu items were not found.", errors={"menu_item_id": missing}, status=400)
        )

    unavailable = [str(mid) for mid, mi in menu_items.items() if not mi.available]
    if unavailable:
        raise _CartError(
            fail(
                "Some menu items are unavailable.",
                errors={"menu_item_id": unavailable},
                status=400,
            )
        )

    total = sum(menu_items[mid].price * qty for mid, qty in wanted.items())
    return wanted, menu_items, total


class MenuItemListCreateView(ListCreateAPIView):
    """GET: browse the menu (any authenticated user).
    POST: add a menu item (canteen_owner/admin)."""

    serializer_class = MenuItemSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [role_required(*_STAFF_ROLES)()]
        return [IsAuthenticated()]

    def get_queryset(self):
        return MenuItem.objects.all().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.tenant_id)


class MenuItemDetailView(RetrieveUpdateAPIView):
    """GET/PATCH a single menu item. Mutations are canteen_owner/admin only
    (owner toggles ``available`` / edits price/name)."""

    serializer_class = MenuItemSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH"):
            return [role_required(*_STAFF_ROLES)()]
        return [IsAuthenticated()]

    def get_queryset(self):
        return MenuItem.objects.all()


class OrderListCreateView(ListCreateAPIView):
    """GET: list orders (role-scoped, 30-day window). POST: place an order.

    Single class so both methods share the ``orders/`` path; permissions are
    split per-method (GET any authenticated, POST student-only).
    """

    serializer_class = OrderSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [role_required("student")()]
        return [IsAuthenticated()]

    def get_queryset(self):
        window_start = timezone.now() - timedelta(days=ORDER_RETENTION_DAYS)
        qs = Order.objects.filter(created_at__gte=window_start).prefetch_related(
            "items", "items__menu_item"
        )
        role = getattr(self.request.user, "role", None)
        if role == "student":
            qs = qs.filter(student_id=self.request.user.id)
        # canteen_owner/admin: full tenant queue in window (no student filter).
        return qs.order_by("-created_at")

    def create(self, request, *args, **kwargs):
        in_ser = OrderCreateSerializer(data=request.data)
        if not in_ser.is_valid():
            return fail("Invalid order.", errors=in_ser.errors, status=400)

        items = in_ser.validated_data["items"]
        order_id = in_ser.validated_data.get("razorpay_order_id")
        payment_id = in_ser.validated_data.get("razorpay_payment_id")
        signature = in_ser.validated_data.get("razorpay_signature")
        has_razorpay_proof = all((order_id, payment_id, signature))

        # Real Razorpay path: verify the client's proof-of-payment before
        # creating the order. When the fields are absent (simulated/dev/test
        # mode) verification is skipped and the order is created directly,
        # exactly as before this payment step existed.
        gateway_ref = ""
        if has_razorpay_proof and razorpay_gateway.is_configured():
            if not razorpay_gateway.verify_signature(order_id, payment_id, signature):
                return fail("Payment verification failed.", status=400)
            gateway_ref = payment_id

        with transaction.atomic():
            try:
                wanted, menu_items, total = _resolve_cart(items)
            except _CartError as exc:
                return exc.response

            order = Order.objects.create(
                tenant_id=request.tenant_id,
                student_id=request.user.id,
                status=Order.Status.PLACED,
                total=total,
                gateway_ref=gateway_ref,
            )
            OrderItem.objects.bulk_create(
                [
                    OrderItem(
                        tenant_id=request.tenant_id,
                        order=order,
                        menu_item=menu_items[mid],
                        quantity=qty,
                        unit_price=menu_items[mid].price,
                    )
                    for mid, qty in wanted.items()
                ]
            )

        return ok(OrderSerializer(order).data, message="Order placed.", status=201)


class OrderCheckoutView(APIView):
    """POST /api/v1/orders/checkout — price a cart and open a Razorpay order.

    Student-only. Validates the cart exactly like order creation (items exist,
    belong to the tenant, are ``available``) and computes the total
    server-side, but creates NO Order/OrderItem rows — it only returns what a
    frontend needs to open the Razorpay checkout widget.

    When Razorpay is configured, returns a real Razorpay order. When it is NOT
    (local/dev/test), returns a simulated order (``order_id`` prefixed
    ``SIM-`` and an empty ``key_id``) so the checkout flow can be exercised
    end-to-end without real credentials.
    """

    permission_classes = [role_required("student")]

    def post(self, request):
        in_ser = CheckoutSerializer(data=request.data)
        if not in_ser.is_valid():
            return fail("Invalid checkout.", errors=in_ser.errors, status=400)

        try:
            _wanted, _menu_items, total = _resolve_cart(in_ser.validated_data["items"])
        except _CartError as exc:
            return exc.response

        if razorpay_gateway.is_configured():
            receipt = f"cart-{request.user.id}-{int(timezone.now().timestamp())}"
            order = razorpay_gateway.create_order(total, receipt=receipt)
        else:
            order = {
                "order_id": f"SIM-{uuid.uuid4()}",
                "amount": str(total),
                "currency": "INR",
                "key_id": "",
            }
        return ok(order, message="Checkout order created.")


class OrderStatusUpdateView(APIView):
    """PATCH /orders/<id>/status/ — advance an order along a legal transition.

    canteen_owner/admin only. Body: ``{"status": "<new status>"}``.
    """

    permission_classes = [role_required(*_STAFF_ROLES)]

    def patch(self, request, pk):
        new_status = request.data.get("status")
        valid = {s.value for s in Order.Status}
        if new_status not in valid:
            return fail(
                "Invalid status.", errors={"status": f"Must be one of {sorted(valid)}."}, status=400
            )

        try:
            order = Order.objects.get(pk=pk)
        except Order.DoesNotExist:
            return fail("Order not found.", status=404)

        if new_status not in _ALLOWED_TRANSITIONS[order.status]:
            return fail(
                f"Cannot transition from '{order.status}' to '{new_status}'.",
                errors={"status": "Illegal transition."},
                status=400,
            )

        order.status = new_status
        order.save(update_fields=["status", "updated_at"])
        return ok(OrderSerializer(order).data, message="Order status updated.")
