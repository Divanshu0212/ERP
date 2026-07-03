"""Serializers for the in-app inbox (Task 5.2).

Response shaping only — the inbox's per-user/tenant filtering lives in
``notify.views``.
"""

from notify.models import Notification
from rest_framework import serializers


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "body", "read", "created_at"]
        read_only_fields = fields
