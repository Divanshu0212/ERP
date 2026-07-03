# Prototype/stub service — basic tenant-aware CRUD only; full feature set designed in the capstone spec, not implemented in this pass.
"""Student list/create endpoint (prototype/stub)."""

from rest_framework.generics import ListCreateAPIView
from students.models import StudentProfile
from students.serializers import StudentProfileSerializer


class StudentProfileListCreateView(ListCreateAPIView):
    serializer_class = StudentProfileSerializer

    def get_queryset(self):
        return StudentProfile.objects.all().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.tenant_id)
