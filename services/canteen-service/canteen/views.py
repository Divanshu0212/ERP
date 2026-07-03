# Prototype/stub service — basic tenant-aware CRUD only; full feature set designed in the capstone spec, not implemented in this pass.
"""Menu item list/create endpoint (prototype/stub)."""

from canteen.models import MenuItem
from canteen.serializers import MenuItemSerializer
from rest_framework.generics import ListCreateAPIView


class MenuItemListCreateView(ListCreateAPIView):
    serializer_class = MenuItemSerializer

    def get_queryset(self):
        return MenuItem.objects.all().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.tenant_id)
