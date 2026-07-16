"""URL configuration for student-service."""

from django.urls import include, path

urlpatterns = [
    path("api/v1/students/", include("students.urls")),
    path("", include("django_prometheus.urls")),
]
