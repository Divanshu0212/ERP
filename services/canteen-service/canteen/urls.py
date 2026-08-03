"""Canteen endpoints, included under /api/v1/ from config.urls.

Menu items and orders are separate gateway prefixes (/api/v1/menu-items/ and
/api/v1/orders/), both routed to canteen-service — so the full paths are
declared here rather than under a single resource include.
"""

from canteen.views import (
    MenuItemDetailView,
    MenuItemListCreateView,
    OrderCheckoutView,
    OrderListCreateView,
    OrderStatusUpdateView,
    PickupScanView,
    PickupTokenView,
)
from django.urls import path

urlpatterns = [
    path("menu-items/", MenuItemListCreateView.as_view(), name="menu-item-list-create"),
    path("menu-items/<uuid:pk>/", MenuItemDetailView.as_view(), name="menu-item-detail"),
    path("orders/checkout", OrderCheckoutView.as_view(), name="order-checkout"),
    # Before any orders/<uuid:pk> pattern so it is not read as a detail route.
    path("orders/pickup", PickupScanView.as_view(), name="order-pickup"),
    path(
        "orders/<uuid:pk>/pickup-token",
        PickupTokenView.as_view(),
        name="order-pickup-token",
    ),
    path("orders/", OrderListCreateView.as_view(), name="order-list-create"),
    path("orders/<uuid:pk>/status/", OrderStatusUpdateView.as_view(), name="order-status-update"),
]
