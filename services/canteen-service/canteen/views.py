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

from datetime import timedelta

from canteen.models import MenuItem, Order, OrderItem
from canteen.serializers import (
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
        # Collapse duplicate menu_item_ids into summed quantities.
        wanted = {}
        for line in items:
            wanted[line["menu_item_id"]] = wanted.get(line["menu_item_id"], 0) + line["quantity"]

        with transaction.atomic():
            # ``objects`` is tenant-scoped, so cross-tenant ids simply aren't
            # found here — no cross-tenant leak.
            menu_items = {mi.id: mi for mi in MenuItem.objects.filter(id__in=list(wanted.keys()))}

            missing = [str(mid) for mid in wanted if mid not in menu_items]
            if missing:
                return fail(
                    "Some menu items were not found.", errors={"menu_item_id": missing}, status=400
                )

            unavailable = [str(mid) for mid, mi in menu_items.items() if not mi.available]
            if unavailable:
                return fail(
                    "Some menu items are unavailable.",
                    errors={"menu_item_id": unavailable},
                    status=400,
                )

            total = sum(menu_items[mid].price * qty for mid, qty in wanted.items())

            order = Order.objects.create(
                tenant_id=request.tenant_id,
                student_id=request.user.id,
                status=Order.Status.PLACED,
                total=total,
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
