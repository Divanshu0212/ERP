"""Library endpoints, included under /api/v1/books/ from config.urls."""

from django.urls import path
from library.views import BookListCreateView

urlpatterns = [
    path("", BookListCreateView.as_view(), name="book-list-create"),
]
