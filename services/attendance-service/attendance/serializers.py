"""Serializer for AttendanceRecord (prototype/stub)."""

from attendance.models import AttendanceRecord
from rest_framework import serializers


class AttendanceRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceRecord
        fields = ["id", "student_id", "course_id", "date", "status", "created_at"]
        read_only_fields = ["id", "created_at"]
