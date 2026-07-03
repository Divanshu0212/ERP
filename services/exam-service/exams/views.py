# Prototype/stub service — basic tenant-aware CRUD only; full feature set designed in the capstone spec, not implemented in this pass.
"""Exam schedule list/create endpoint (prototype/stub)."""

from exams.models import ExamSchedule
from exams.serializers import ExamScheduleSerializer
from rest_framework.generics import ListCreateAPIView


class ExamScheduleListCreateView(ListCreateAPIView):
    serializer_class = ExamScheduleSerializer

    def get_queryset(self):
        return ExamSchedule.objects.all().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.tenant_id)
