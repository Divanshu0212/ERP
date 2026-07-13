"""Serializers for the allocate endpoint and room/allocation listings.

Request validation and response shaping only — the allocate flow's actual
capacity-check/atomic-commit/outbox logic lives in ``hostel.views.AllocateView``.
"""

from hostel.models import (
    Allocation,
    AllocationImportBatch,
    AllocationImportRow,
    Block,
    Room,
    RoomRequest,
)
from rest_framework import serializers


class AllocateRequestSerializer(serializers.Serializer):
    room_id = serializers.UUIDField()
    student_user_code = serializers.RegexField(r"^[A-Za-z0-9_-]{1,30}$")


class AllocationSerializer(serializers.ModelSerializer):
    room_id = serializers.UUIDField(source="room.id", read_only=True)
    room_name = serializers.SerializerMethodField()

    class Meta:
        model = Allocation
        fields = ["id", "status", "room_id", "room_name", "student_user_code", "allocated_on"]
        read_only_fields = fields

    def get_room_name(self, obj):
        return f"{obj.room.block.name} - {obj.room.room_no}"


class RoomSerializer(serializers.ModelSerializer):
    is_available = serializers.BooleanField(read_only=True)
    block_name = serializers.CharField(source="block.name", read_only=True)

    class Meta:
        model = Room
        fields = [
            "id",
            "block",
            "block_name",
            "room_no",
            "capacity",
            "occupied_count",
            "is_available",
        ]
        read_only_fields = fields


class BlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Block
        fields = ["id", "name", "gender_type", "warden_id", "created_at"]
        read_only_fields = fields


class BlockCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    gender_type = serializers.ChoiceField(choices=Block.GenderType.choices)
    warden_user_code = serializers.RegexField(r"^[A-Za-z0-9_-]{1,30}$")


class RoomCreateSerializer(serializers.Serializer):
    block_id = serializers.UUIDField()
    room_no = serializers.CharField(max_length=50)
    capacity = serializers.IntegerField(min_value=1, default=2)


class RoomCapacityUpdateSerializer(serializers.Serializer):
    capacity = serializers.IntegerField(min_value=1)


class AllocationImportRowSerializer(serializers.ModelSerializer):
    allocation_id = serializers.SerializerMethodField()

    class Meta:
        model = AllocationImportRow
        fields = [
            "row_number",
            "room_id_raw",
            "student_user_code_raw",
            "status",
            "error_message",
            "allocation_id",
        ]
        read_only_fields = fields

    def get_allocation_id(self, obj):
        return str(obj.allocation_id) if obj.allocation_id else None


class AllocationImportBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = AllocationImportBatch
        fields = [
            "id",
            "filename",
            "total_rows",
            "success_count",
            "fail_count",
            "skipped_count",
            "created_at",
        ]
        read_only_fields = fields


class AllocationImportBatchDetailSerializer(AllocationImportBatchSerializer):
    rows = AllocationImportRowSerializer(many=True, read_only=True)

    class Meta(AllocationImportBatchSerializer.Meta):
        fields = AllocationImportBatchSerializer.Meta.fields + ["rows"]


class RoomRequestCreateSerializer(serializers.Serializer):
    room_id = serializers.UUIDField()


class RoomRequestSerializer(serializers.ModelSerializer):
    room_id = serializers.UUIDField(source="room.id", read_only=True)
    room_name = serializers.SerializerMethodField()

    class Meta:
        model = RoomRequest
        fields = [
            "id",
            "student_user_code",
            "room_id",
            "room_name",
            "status",
            "requested_on",
            "decided_on",
            "rejection_reason",
        ]
        read_only_fields = fields

    def get_room_name(self, obj):
        return f"{obj.room.block.name} - {obj.room.room_no}"


class RoomRequestApproveSerializer(serializers.Serializer):
    fee_structure_id = serializers.UUIDField()


class RoomRequestRejectSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(max_length=500, required=False, default="")
