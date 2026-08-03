"""Hostel endpoints: allocate, rooms, blocks, allocations, bulk import,
import logs. Included under /api/v1/hostel/ from config.urls.
"""

from django.urls import path
from hostel.views import (
    AllocateBulkView,
    AllocateView,
    AllocationImportLogDetailView,
    AllocationImportLogListView,
    AllocationListView,
    ApproveRoomRequestView,
    AvailableRoomsTemplateView,
    AvailableRoomsView,
    BlockListCreateView,
    MyAllocationsView,
    MyRoomRequestsView,
    RejectRoomRequestView,
    ReleaseAllocationView,
    RoomDetailView,
    RoomListCreateView,
    RoomRequestListCreateView,
    VisitorCheckoutView,
    VisitorLogListCreateView,
)

urlpatterns = [
    path("allocate", AllocateView.as_view(), name="allocate"),
    path("allocate/bulk", AllocateBulkView.as_view(), name="allocate-bulk"),
    path(
        "rooms/available-template",
        AvailableRoomsTemplateView.as_view(),
        name="rooms-available-template",
    ),
    path("rooms/available", AvailableRoomsView.as_view(), name="rooms-available"),
    path("rooms", RoomListCreateView.as_view(), name="room-list-create"),
    path("rooms/<uuid:pk>", RoomDetailView.as_view(), name="room-detail"),
    path("blocks", BlockListCreateView.as_view(), name="block-list-create"),
    # Before the tenant-wide list so "mine" is never read as a lookup value.
    path("allocations/mine", MyAllocationsView.as_view(), name="allocation-mine"),
    path("allocations", AllocationListView.as_view(), name="allocation-list"),
    path(
        "allocations/<uuid:pk>/release",
        ReleaseAllocationView.as_view(),
        name="allocation-release",
    ),
    path(
        "allocations/import-logs",
        AllocationImportLogListView.as_view(),
        name="allocation-import-log-list",
    ),
    path(
        "allocations/import-logs/<uuid:pk>",
        AllocationImportLogDetailView.as_view(),
        name="allocation-import-log-detail",
    ),
    path("room-requests/mine", MyRoomRequestsView.as_view(), name="room-request-mine"),
    path("room-requests", RoomRequestListCreateView.as_view(), name="room-request-list-create"),
    path(
        "room-requests/<uuid:pk>/approve",
        ApproveRoomRequestView.as_view(),
        name="room-request-approve",
    ),
    path(
        "room-requests/<uuid:pk>/reject",
        RejectRoomRequestView.as_view(),
        name="room-request-reject",
    ),
    path("visitors", VisitorLogListCreateView.as_view(), name="visitor-list-create"),
    path(
        "visitors/<uuid:pk>/checkout",
        VisitorCheckoutView.as_view(),
        name="visitor-checkout",
    ),
]
