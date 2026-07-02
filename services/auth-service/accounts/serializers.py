"""Serializers for register/login/me.

JWT issuance itself lives in ``accounts.views`` (tokens are built manually
with ``RefreshToken.for_user`` so the tenant-scoped ``TenantAuthBackend`` can
be invoked explicitly) — these serializers only handle request validation
and response shaping.
"""

from accounts.models import Institution, User
from rest_framework import serializers


class RegisterSerializer(serializers.Serializer):
    institution_slug = serializers.SlugField()
    email = serializers.EmailField()
    password = serializers.CharField(
        write_only=True, min_length=8, style={"input_type": "password"}
    )
    role = serializers.ChoiceField(
        choices=User.Role.choices, required=False, default=User.Role.STUDENT
    )

    def validate_institution_slug(self, value):
        try:
            institution = Institution.objects.get(slug=value)
        except Institution.DoesNotExist as exc:
            raise serializers.ValidationError("Unknown institution.") from exc
        if not institution.is_active:
            raise serializers.ValidationError("Institution is not active.")
        self._institution = institution
        return value

    def validate(self, attrs):
        institution = getattr(self, "_institution", None)
        email = User.objects.normalize_email(attrs["email"])
        if institution and User.objects.filter(tenant=institution, email=email).exists():
            raise serializers.ValidationError({"email": "A user with this email already exists."})
        return attrs

    def create(self, validated_data):
        institution = self._institution
        return User.objects.create_user(
            tenant=institution,
            email=validated_data["email"],
            password=validated_data["password"],
            role=validated_data.get("role", User.Role.STUDENT),
        )


class LoginSerializer(serializers.Serializer):
    institution_slug = serializers.SlugField()
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class MeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    role = serializers.CharField()
    tenant = serializers.CharField()
