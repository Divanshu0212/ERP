"""Attendance endpoints, included under /api/v1/attendance/ from config.urls."""

from attendance.views import (
    AttendanceRecordListCreateView,
    AttendanceSummaryView,
    MarkAttendanceView,
    SessionCloseView,
    SessionCodeView,
    SessionCreateView,
    SessionMarksView,
)
from django.urls import path

urlpatterns = [
    path("", AttendanceRecordListCreateView.as_view(), name="attendance-list-create"),
    path("sessions", SessionCreateView.as_view(), name="session-create"),
    path("sessions/<uuid:pk>/close", SessionCloseView.as_view(), name="session-close"),
    path("sessions/<uuid:pk>/code", SessionCodeView.as_view(), name="session-code"),
    path("sessions/<uuid:pk>/mark", MarkAttendanceView.as_view(), name="session-mark"),
    path("sessions/<uuid:pk>/marks", SessionMarksView.as_view(), name="session-marks"),
    path("summary", AttendanceSummaryView.as_view(), name="attendance-summary"),
]
