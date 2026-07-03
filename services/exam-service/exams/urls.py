"""Exam endpoints, included under /api/v1/exams/ from config.urls."""

from django.urls import path
from exams.views import ExamScheduleListCreateView

urlpatterns = [
    path("", ExamScheduleListCreateView.as_view(), name="exam-list-create"),
]
