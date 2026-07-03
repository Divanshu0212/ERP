"""Serializer for Book (prototype/stub)."""

from library.models import Book
from rest_framework import serializers


class BookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Book
        fields = [
            "id",
            "isbn",
            "title",
            "author",
            "category",
            "total_copies",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
