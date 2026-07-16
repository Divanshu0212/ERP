"""URL configuration for analytics-service."""

from django.urls import include, path

urlpatterns = [
    path("api/v1/metrics/", include("analytics.urls")),
    path("", include("django_prometheus.urls")),
]
