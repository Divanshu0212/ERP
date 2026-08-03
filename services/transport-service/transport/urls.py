"""Transport endpoints (Task 6.3): routes, per-route seats, bookings.

Included under /api/v1/transport/ from config.urls.
"""

from django.urls import path

from .views import (
    BookingCreateView,
    BreadcrumbIngestView,
    DriverScheduleListView,
    LivePositionView,
    MyPassQrView,
    RouteListView,
    RouteSeatsView,
    ScanKeyView,
    ScanView,
    ScheduleBookingsView,
    TripEndView,
    TripStartView,
)

urlpatterns = [
    path("routes", RouteListView.as_view(), name="route-list"),
    path("routes/<uuid:route_id>/seats", RouteSeatsView.as_view(), name="route-seats"),
    path("routes/<uuid:route_id>/live", LivePositionView.as_view(), name="route-live"),
    path("bookings", BookingCreateView.as_view(), name="booking-create"),
    path("passes/mine/qr", MyPassQrView.as_view(), name="my-pass-qr"),
    path("scan-key", ScanKeyView.as_view(), name="scan-key"),
    path("scans", ScanView.as_view(), name="scan-create"),
    path("schedules/mine", DriverScheduleListView.as_view(), name="driver-schedules"),
    path(
        "schedules/<uuid:schedule_id>/bookings",
        ScheduleBookingsView.as_view(),
        name="schedule-bookings",
    ),
    path("schedules/<uuid:schedule_id>/trips", TripStartView.as_view(), name="trip-start"),
    path("trips/<uuid:pk>/end", TripEndView.as_view(), name="trip-end"),
    path("trips/<uuid:pk>/breadcrumbs", BreadcrumbIngestView.as_view(), name="trip-breadcrumbs"),
]
