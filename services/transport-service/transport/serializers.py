"""Serializers for route listing and the booking endpoint.

Request validation and response shaping only — the booking flow's actual
uniqueness/idempotency/atomic-commit logic lives in
``transport.views.BookingCreateView``.
"""

from rest_framework import serializers

from .models import Booking, BusSchedule, Route


class RouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Route
        fields = ["id", "name", "start_point", "end_point", "created_at"]
        read_only_fields = fields


class _RouteNestedSerializer(serializers.ModelSerializer):
    """Compact route summary nested inside a schedule."""

    class Meta:
        model = Route
        fields = ["id", "name", "start_point", "end_point"]
        read_only_fields = fields


class BusScheduleSerializer(serializers.ModelSerializer):
    """A driver's (or admin's) view of a bus schedule, with live booked count."""

    route = _RouteNestedSerializer(read_only=True)
    booked_count = serializers.SerializerMethodField()

    class Meta:
        model = BusSchedule
        fields = [
            "id",
            "route",
            "bus_no",
            "driver_id",
            "departure_time",
            "capacity",
            "booked_count",
        ]
        read_only_fields = fields

    def get_booked_count(self, obj) -> int:
        return obj.bookings.filter(status="booked").count()


class BookingRequestSerializer(serializers.Serializer):
    schedule_id = serializers.UUIDField()
    seat_no = serializers.IntegerField(min_value=1)
    idempotency_key = serializers.CharField(max_length=255, required=False, allow_blank=False)
    # Optional: falls back to the JWT ``sub`` claim when omitted.
    student_user_code = serializers.RegexField(r"^[A-Za-z0-9_-]{1,30}$", required=False)


class BookingSerializer(serializers.ModelSerializer):
    schedule_id = serializers.UUIDField(source="schedule.id", read_only=True)

    class Meta:
        model = Booking
        fields = ["id", "schedule_id", "student_user_code", "seat_no", "status", "created_at"]
        read_only_fields = fields
