"""Hostel endpoints (Task 4.8): allocate, rooms/available, allocations.

Included under /api/v1/hostel/ from config.urls.
"""

from django.urls import path
from hostel.views import AllocateView, AllocationListView, AvailableRoomsView

urlpatterns = [
    path("allocate", AllocateView.as_view(), name="allocate"),
    path("rooms/available", AvailableRoomsView.as_view(), name="rooms-available"),
    path("allocations", AllocationListView.as_view(), name="allocation-list"),
]
