"""Grievance endpoints (Task 6.5): create/list, retrieve.

Included under /api/v1/ from config.urls, giving /api/v1/grievance and
/api/v1/grievance/{id} (no trailing slash, matching the other services).
"""

from django.urls import path
from grievance.views import GrievanceDetailView, GrievanceListCreateView

urlpatterns = [
    path("grievance", GrievanceListCreateView.as_view(), name="grievance-list-create"),
    path("grievance/<uuid:ticket_id>", GrievanceDetailView.as_view(), name="grievance-detail"),
]
