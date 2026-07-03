"""Serializers for the grievance create/list/retrieve endpoints.

Request validation and response shaping only — the create flow's actual
atomic-commit/outbox logic lives in ``grievance.views.GrievanceCreateView``.
"""

from grievance.models import Ticket
from rest_framework import serializers


class GrievanceCreateRequestSerializer(serializers.Serializer):
    category = serializers.CharField(max_length=50)
    description = serializers.CharField()


class TicketSerializer(serializers.ModelSerializer):
    class Meta:
        model = Ticket
        fields = [
            "id",
            "raised_by",
            "category",
            "description",
            "sentiment_score",
            "urgency",
            "status",
            "assigned_to",
            "created_at",
        ]
        read_only_fields = fields
