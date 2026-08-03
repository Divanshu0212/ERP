"""Serializers for the day roll and for geofenced sessions."""

from attendance.models import AttendanceMark, AttendanceRecord, Session
from rest_framework import serializers


class AttendanceRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceRecord
        fields = ["id", "student_user_code", "course_id", "date", "status", "created_at"]
        read_only_fields = ["id", "created_at"]


class SessionCreateSerializer(serializers.Serializer):
    course_code = serializers.CharField(max_length=50)
    lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6)
    radius_m = serializers.IntegerField(min_value=10, max_value=500, default=50)


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Session
        fields = [
            "id",
            "course_code",
            "faculty_id",
            "lat",
            "lng",
            "radius_m",
            "opened_at",
            "closed_at",
        ]
        read_only_fields = fields


class MarkRequestSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    code = serializers.CharField(max_length=10)
    mock_location = serializers.BooleanField(default=False)


class AttendanceMarkSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceMark
        fields = [
            "id",
            "session",
            "student_user_code",
            "distance_m",
            "mock_location",
            "marked_at",
        ]
        read_only_fields = fields
