"""Serializer for Drive (prototype/stub)."""

from placement.models import Drive
from rest_framework import serializers


class DriveSerializer(serializers.ModelSerializer):
    class Meta:
        model = Drive
        fields = [
            "id",
            "company_name",
            "job_title",
            "ctc",
            "eligibility",
            "drive_date",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
