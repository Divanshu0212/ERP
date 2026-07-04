"""Serializers for canteen menu items and orders.

Input serializers (``OrderItemInputSerializer``/``OrderCreateSerializer``)
validate the request body only; the order-building/price-snapshot/total logic
lives in ``canteen.views.OrderListCreateView``. Output serializers
(``OrderItemSerializer``/``OrderSerializer``) shape the response.
"""

from canteen.models import MenuItem, Order, OrderItem
from rest_framework import serializers


class MenuItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuItem
        fields = ["id", "name", "price", "available", "created_at"]
        read_only_fields = ["id", "created_at"]


class OrderItemInputSerializer(serializers.Serializer):
    """One line of an incoming order request (body only)."""

    menu_item_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)


class OrderCreateSerializer(serializers.Serializer):
    """Incoming order request: a non-empty list of line items.

    Optional Razorpay proof-of-payment fields. When all three are present and
    Razorpay is configured, the signature is verified before the order is
    created; when absent (simulated/dev/test mode) the order is created
    directly, preserving the pre-payment behavior.
    """

    items = OrderItemInputSerializer(many=True)
    razorpay_order_id = serializers.CharField(max_length=255, required=False)
    razorpay_payment_id = serializers.CharField(max_length=255, required=False)
    razorpay_signature = serializers.CharField(max_length=255, required=False)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("An order must contain at least one item.")
        return value


class CheckoutSerializer(serializers.Serializer):
    """Incoming checkout request: a non-empty list of line items (no order is
    created — this only prices the cart and opens a Razorpay order)."""

    items = OrderItemInputSerializer(many=True)

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("A checkout must contain at least one item.")
        return value


class OrderItemSerializer(serializers.ModelSerializer):
    """Output shape for a single order line, with the menu item snapshot."""

    menu_item_id = serializers.UUIDField(source="menu_item.id", read_only=True)
    name = serializers.CharField(source="menu_item.name", read_only=True)

    class Meta:
        model = OrderItem
        fields = ["id", "menu_item_id", "name", "quantity", "unit_price"]
        read_only_fields = fields


class OrderSerializer(serializers.ModelSerializer):
    """Output shape for an order and its nested line items."""

    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ["id", "student_id", "status", "total", "items", "created_at", "updated_at"]
        read_only_fields = fields
