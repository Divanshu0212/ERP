"""Serializer for MetricSnapshot (prototype/stub)."""

from analytics.models import MetricSnapshot
from rest_framework import serializers


class MetricSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetricSnapshot
        fields = ["id", "metric", "value", "captured_at"]
        read_only_fields = ["id", "captured_at"]
