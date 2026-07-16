"""URL configuration for canteen-service."""

from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("canteen.urls")),
    path("", include("django_prometheus.urls")),
]
