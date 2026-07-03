"""Serializer for MenuItem (prototype/stub)."""

from canteen.models import MenuItem
from rest_framework import serializers


class MenuItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuItem
        fields = ["id", "name", "price", "available", "created_at"]
        read_only_fields = ["id", "created_at"]
