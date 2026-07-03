# Prototype/stub service — basic tenant-aware CRUD only; full feature set designed in the capstone spec, not implemented in this pass.
"""Book list/create endpoint (prototype/stub)."""

from library.models import Book
from library.serializers import BookSerializer
from rest_framework.generics import ListCreateAPIView


class BookListCreateView(ListCreateAPIView):
    serializer_class = BookSerializer

    def get_queryset(self):
        return Book.objects.all().order_by("-created_at")

    def perform_create(self, serializer):
        serializer.save(tenant_id=self.request.tenant_id)
