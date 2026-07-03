"""Placement endpoints, included under /api/v1/drives/ from config.urls."""

from django.urls import path
from placement.views import DriveListCreateView

urlpatterns = [
    path("", DriveListCreateView.as_view(), name="drive-list-create"),
]
