"""Student endpoints, included under /api/v1/students/ from config.urls."""

from django.urls import path
from students.views import StudentProfileListCreateView

urlpatterns = [
    path("", StudentProfileListCreateView.as_view(), name="student-list-create"),
]
