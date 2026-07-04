"""Serializers for the allocate endpoint and room/allocation listings.

Request validation and response shaping only — the allocate flow's actual
capacity-check/atomic-commit/outbox logic lives in ``hostel.views.AllocateView``.
"""

from hostel.models import Allocation, AllocationImportBatch, AllocationImportRow, Room
from rest_framework import serializers


class AllocateRequestSerializer(serializers.Serializer):
    room_id = serializers.UUIDField()
    student_email = serializers.EmailField()


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


class AllocationImportRowSerializer(serializers.ModelSerializer):
    allocation_id = serializers.SerializerMethodField()

    class Meta:
        model = AllocationImportRow
        fields = ["row_number", "room_id_raw", "student_email_raw", "status", "error_message", "allocation_id"]
        read_only_fields = fields

    def get_allocation_id(self, obj):
        return str(obj.allocation_id) if obj.allocation_id else None


class AllocationImportBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = AllocationImportBatch
        fields = ["id", "filename", "total_rows", "success_count", "fail_count", "created_at"]
        read_only_fields = fields


class AllocationImportBatchDetailSerializer(AllocationImportBatchSerializer):
    rows = AllocationImportRowSerializer(many=True, read_only=True)

    class Meta(AllocationImportBatchSerializer.Meta):
        fields = AllocationImportBatchSerializer.Meta.fields + ["rows"]
