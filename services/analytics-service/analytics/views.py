# Prototype/stub service — basic tenant-aware CRUD only; full feature set designed in the capstone spec, not implemented in this pass.
"""Metric snapshot list/create endpoint (prototype/stub)."""

from analytics.models import MetricSnapshot
from analytics.serializers import MetricSnapshotSerializer
from rest_framework.generics import ListCreateAPIView


class MetricSnapshotListCreateView(ListCreateAPIView):
    serializer_class = MetricSnapshotSerializer

    def get_queryset(self):
        return MetricSnapshot.objects.all().order_by("-captured_at")

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.tenant_id)
