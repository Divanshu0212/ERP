"""Canteen endpoints, included under /api/v1/menu-items/ from config.urls."""

from canteen.views import MenuItemListCreateView
from django.urls import path

urlpatterns = [
    path("", MenuItemListCreateView.as_view(), name="menu-item-list-create"),
]
