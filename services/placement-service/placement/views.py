# Prototype/stub service — basic tenant-aware CRUD only; full feature set designed in the capstone spec, not implemented in this pass.
"""Drive list/create endpoint (prototype/stub)."""

from placement.models import Drive
from placement.serializers import DriveSerializer
from rest_framework.generics import ListCreateAPIView


class DriveListCreateView(ListCreateAPIView):
    serializer_class = DriveSerializer

    def get_queryset(self):
        return Drive.objects.all().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.tenant_id)
