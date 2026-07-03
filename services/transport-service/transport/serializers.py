"""Serializers for route listing and the booking endpoint.

Request validation and response shaping only — the booking flow's actual
uniqueness/idempotency/atomic-commit logic lives in
``transport.views.BookingCreateView``.
"""

from rest_framework import serializers

from .models import Booking, Route


class RouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Route
        fields = ["id", "name", "start_point", "end_point", "created_at"]
        read_only_fields = fields


class BookingRequestSerializer(serializers.Serializer):
    schedule_id = serializers.UUIDField()
    seat_no = serializers.IntegerField(min_value=1)
    idempotency_key = serializers.CharField(max_length=255, required=False, allow_blank=False)
    # Optional: falls back to the JWT ``sub`` claim when omitted.
    student_id = serializers.UUIDField(required=False)


class BookingSerializer(serializers.ModelSerializer):
    schedule_id = serializers.UUIDField(source="schedule.id", read_only=True)

    class Meta:
        model = Booking
        fields = ["id", "schedule_id", "student_id", "seat_no", "status", "created_at"]
        read_only_fields = fields
