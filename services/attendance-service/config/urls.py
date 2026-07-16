"""URL configuration for attendance-service."""

from django.urls import include, path

urlpatterns = [
    path("api/v1/attendance/", include("attendance.urls")),
    path("", include("django_prometheus.urls")),
]
