"""Serializer for ExamSchedule (prototype/stub)."""

from exams.models import ExamSchedule
from rest_framework import serializers


class ExamScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExamSchedule
        fields = [
            "id",
            "course_id",
            "exam_date",
            "room_no",
            "duration_minutes",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
