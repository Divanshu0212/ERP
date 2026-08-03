"""Serializers for the grievance create/list/retrieve endpoints.

Request validation and response shaping only — the create flow's actual
atomic-commit/outbox logic lives in ``grievance.views.GrievanceCreateView``.
"""

from grievance.models import Ticket, TicketMedia
from rest_framework import serializers


class GrievanceCreateRequestSerializer(serializers.Serializer):
    category = serializers.CharField(max_length=50)
    description = serializers.CharField()


class TicketSerializer(serializers.ModelSerializer):
    #: Summarised rather than nested: a ticket row needs to say "2 attachments,
    #: purged on the 9th" without the client fetching every blob's metadata.
    media_count = serializers.SerializerMethodField()
    media_purged_at = serializers.SerializerMethodField()

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
            "media_count",
            "media_purged_at",
        ]
        read_only_fields = fields

    def get_media_count(self, obj) -> int:
        return obj.media.count()

    def get_media_purged_at(self, obj):
        """When the evidence was deleted, or None while it is still held."""
        purged = obj.media.filter(purged_at__isnull=False).order_by("-purged_at").first()
        return purged.purged_at if purged else None


class TicketMediaSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = TicketMedia
        fields = ["id", "url", "sha256", "captured_at", "expires_at", "purged_at"]
        read_only_fields = fields

    def get_url(self, obj):
        """None once purged — the row survives, the file does not."""
        return obj.file.url if obj.file else None
