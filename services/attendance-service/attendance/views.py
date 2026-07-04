# Prototype/stub service — basic tenant-aware CRUD only; full feature set designed in the capstone spec, not implemented in this pass.
"""Attendance list/create endpoint (prototype/stub)."""

from attendance.models import AttendanceRecord
from attendance.serializers import AttendanceRecordSerializer
from rest_framework.generics import ListCreateAPIView
from rest_framework.permissions import IsAuthenticated
from suerp_common.permissions import role_required


class AttendanceRecordListCreateView(ListCreateAPIView):
    serializer_class = AttendanceRecordSerializer

    def get_permissions(self):
        # GET: any authenticated user may view. POST: faculty/admin only.
        if self.request.method == "POST":
            return [role_required("faculty", "admin")()]
        return [IsAuthenticated()]

    def get_queryset(self):
        return AttendanceRecord.objects.all().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.tenant_id)
