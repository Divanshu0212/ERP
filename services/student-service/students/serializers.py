"""Serializer for StudentProfile (prototype/stub)."""

from rest_framework import serializers
from students.models import StudentProfile


class StudentProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentProfile
        fields = [
            "id",
            "user_id",
            "roll_no",
            "department",
            "batch",
            "semester",
            "cgpa",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
