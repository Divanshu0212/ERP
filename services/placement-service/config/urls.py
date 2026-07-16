"""URL configuration for placement-service."""

from django.urls import include, path

urlpatterns = [
    path("api/v1/drives/", include("placement.urls")),
    path("", include("django_prometheus.urls")),
]
