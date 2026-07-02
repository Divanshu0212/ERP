"""Serializers for invoice creation/listing and the pay endpoint.

Request validation and response shaping only — the pay flow's actual
charge/atomic-commit/outbox logic lives in ``billing.views.PayView``.
"""

from billing.models import Invoice
from rest_framework import serializers


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ["id", "student_id", "amount", "purpose", "status", "created_at"]
        read_only_fields = ["id", "status", "created_at"]


class InvoiceCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ["student_id", "amount", "purpose"]


class PaySerializer(serializers.Serializer):
    invoice_id = serializers.UUIDField()
    idempotency_key = serializers.CharField(max_length=255)
