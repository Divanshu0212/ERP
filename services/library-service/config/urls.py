"""URL configuration for library-service."""

from django.urls import include, path

urlpatterns = [
    path("api/v1/books/", include("library.urls")),
]
