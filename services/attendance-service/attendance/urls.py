"""Attendance endpoints, included under /api/v1/attendance/ from config.urls."""

from attendance.views import AttendanceRecordListCreateView
from django.urls import path

urlpatterns = [
    path("", AttendanceRecordListCreateView.as_view(), name="attendance-list-create"),
]
