"""Serializers for the allocate endpoint and room/allocation listings.

Request validation and response shaping only — the allocate flow's actual
capacity-check/atomic-commit/outbox logic lives in ``hostel.views.AllocateView``.
"""

from hostel.models import Allocation, Room
from rest_framework import serializers


class AllocateRequestSerializer(serializers.Serializer):
    room_id = serializers.UUIDField()
    student_id = serializers.UUIDField()


class AllocationSerializer(serializers.ModelSerializer):
    room_id = serializers.UUIDField(source="room.id", read_only=True)

    class Meta:
        model = Allocation
        fields = ["id", "status", "room_id", "student_id", "allocated_on"]
        read_only_fields = fields


class RoomSerializer(serializers.ModelSerializer):
    is_available = serializers.BooleanField(read_only=True)

    class Meta:
        model = Room
        fields = ["id", "block", "room_no", "capacity", "occupied_count", "is_available"]
        read_only_fields = fields
