"""URL configuration for exam-service."""

from django.urls import include, path

urlpatterns = [
    path("api/v1/exams/", include("exams.urls")),
]
