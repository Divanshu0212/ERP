"""Hostel endpoints: allocate, rooms/available, allocations, bulk import.

Included under /api/v1/hostel/ from config.urls.
"""

from django.urls import path
from hostel.views import (
    AllocateBulkView,
    AllocateView,
    AllocationImportLogDetailView,
    AllocationImportLogListView,
    AllocationListView,
    AvailableRoomsView,
)

urlpatterns = [
    path("allocate", AllocateView.as_view(), name="allocate"),
    path("allocate/bulk", AllocateBulkView.as_view(), name="allocate-bulk"),
    path("rooms/available", AvailableRoomsView.as_view(), name="rooms-available"),
    path("allocations", AllocationListView.as_view(), name="allocation-list"),
    path("allocations/import-logs", AllocationImportLogListView.as_view(), name="allocation-import-log-list"),
    path(
        "allocations/import-logs/<uuid:pk>",
        AllocationImportLogDetailView.as_view(),
        name="allocation-import-log-detail",
    ),
]
