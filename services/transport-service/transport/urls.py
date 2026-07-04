"""Transport endpoints (Task 6.3): routes, per-route seats, bookings.

Included under /api/v1/transport/ from config.urls.
"""

from django.urls import path

from .views import (
    BookingCreateView,
    DriverScheduleListView,
    RouteListView,
    RouteSeatsView,
    ScheduleBookingsView,
)

urlpatterns = [
    path("routes", RouteListView.as_view(), name="route-list"),
    path("routes/<uuid:route_id>/seats", RouteSeatsView.as_view(), name="route-seats"),
    path("bookings", BookingCreateView.as_view(), name="booking-create"),
    path("schedules/mine", DriverScheduleListView.as_view(), name="driver-schedules"),
    path(
        "schedules/<uuid:schedule_id>/bookings",
        ScheduleBookingsView.as_view(),
        name="schedule-bookings",
    ),
]
