# Prototype/stub service — basic tenant-aware CRUD only; full feature set designed in the capstone spec, not implemented in this pass.
"""Attendance list/create endpoint (prototype/stub)."""

from attendance.models import AttendanceRecord
from attendance.serializers import AttendanceRecordSerializer
from rest_framework.generics import ListCreateAPIView


class AttendanceRecordListCreateView(ListCreateAPIView):
    serializer_class = AttendanceRecordSerializer

    def get_queryset(self):
        return AttendanceRecord.objects.all().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.tenant_id)
