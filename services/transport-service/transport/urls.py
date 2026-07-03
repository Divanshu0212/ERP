"""Transport endpoints (Task 6.3): routes, per-route seats, bookings.

Included under /api/v1/transport/ from config.urls.
"""

from django.urls import path

from .views import BookingCreateView, RouteListView, RouteSeatsView

urlpatterns = [
    path("routes", RouteListView.as_view(), name="route-list"),
    path("routes/<uuid:route_id>/seats", RouteSeatsView.as_view(), name="route-seats"),
    path("bookings", BookingCreateView.as_view(), name="booking-create"),
]
