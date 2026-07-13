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
    user_code = serializers.RegexField(r"^[A-Za-z0-9_-]{1,30}$")
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
        if institution and User.objects.filter(
            tenant=institution, user_code=attrs["user_code"]
        ).exists():
            raise serializers.ValidationError(
                {"user_code": "A user with this user_code already exists."}
            )
        return attrs

    def create(self, validated_data):
        institution = self._institution
        return User.objects.create_user(
            tenant=institution,
            email=validated_data["email"],
            password=validated_data["password"],
            role=validated_data.get("role", User.Role.STUDENT),
            user_code=validated_data["user_code"],
        )


class InstitutionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    slug = serializers.SlugField()
    name = serializers.CharField()
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class UserListSerializer(serializers.Serializer):
    user_code = serializers.CharField(allow_null=True)
    email = serializers.EmailField()
    role = serializers.CharField()
    is_active = serializers.BooleanField()
    date_joined = serializers.DateTimeField()


class UserByCodeSerializer(serializers.Serializer):
    user_code = serializers.CharField()
    email = serializers.EmailField()
    role = serializers.CharField()


class AdminCreateUserSerializer(serializers.Serializer):
    """Admin-side user creation. The tenant is taken from the acting admin's
    JWT claim (passed in as ``institution``), never from the request body."""

    email = serializers.EmailField()
    user_code = serializers.RegexField(r"^[A-Za-z0-9_-]{1,30}$")
    role = serializers.ChoiceField(choices=User.Role.choices)
    password = serializers.CharField(
        write_only=True, min_length=8, style={"input_type": "password"}
    )

    def validate(self, attrs):
        institution = self.context["institution"]
        email = User.objects.normalize_email(attrs["email"])
        if User.objects.filter(tenant=institution, email=email).exists():
            raise serializers.ValidationError({"email": "A user with this email already exists."})
        if User.objects.filter(tenant=institution, user_code=attrs["user_code"]).exists():
            raise serializers.ValidationError(
                {"user_code": "A user with this user_code already exists."}
            )
        attrs["email"] = email
        return attrs

    def create(self, validated_data):
        institution = self.context["institution"]
        return User.objects.create_user(
            tenant=institution,
            email=validated_data["email"],
            password=validated_data["password"],
            role=validated_data["role"],
            user_code=validated_data["user_code"],
        )


class BulkCreateStudentRowSerializer(serializers.Serializer):
    """One row of a bulk student-creation batch. Always creates role=student —
    there is no role field, unlike AdminCreateUserSerializer. Cross-row
    duplicate checks (within the same upload) are enforced via
    context["seen_emails"]/context["seen_user_codes"], mutated by the caller
    (UserBulkCreateView) as each row is accepted, so row 5 catching a
    duplicate of row 2 fails only row 5."""

    email = serializers.EmailField()
    user_code = serializers.RegexField(r"^[A-Za-z0-9_-]{1,30}$")
    password = serializers.CharField(
        write_only=True, min_length=8, style={"input_type": "password"}
    )
    department = serializers.CharField(max_length=100)
    batch = serializers.CharField(max_length=20)
    semester = serializers.IntegerField(default=1, min_value=1)

    def validate(self, attrs):
        institution = self.context["institution"]
        seen_emails = self.context["seen_emails"]
        seen_user_codes = self.context["seen_user_codes"]
        email = User.objects.normalize_email(attrs["email"])
        user_code = attrs["user_code"]

        if email in seen_emails:
            raise serializers.ValidationError({"email": "Duplicate email earlier in this upload."})
        if user_code in seen_user_codes:
            raise serializers.ValidationError(
                {"user_code": "Duplicate user_code earlier in this upload."}
            )
        if User.objects.filter(tenant=institution, email=email).exists():
            raise serializers.ValidationError({"email": "A user with this email already exists."})
        if User.objects.filter(tenant=institution, user_code=user_code).exists():
            raise serializers.ValidationError(
                {"user_code": "A user with this user_code already exists."}
            )
        attrs["email"] = email
        return attrs

    def create(self, validated_data):
        institution = self.context["institution"]
        return User.objects.create_user(
            tenant=institution,
            email=validated_data["email"],
            password=validated_data["password"],
            role=User.Role.STUDENT,
            user_code=validated_data["user_code"],
        )


class InstitutionCreateSerializer(serializers.Serializer):
    """Superadmin-side institution creation. Cross-tenant by design."""

    slug = serializers.SlugField()
    name = serializers.CharField(max_length=255)

    def validate_slug(self, value):
        if Institution.objects.filter(slug=value).exists():
            raise serializers.ValidationError("An institution with this slug already exists.")
        return value

    def create(self, validated_data):
        return Institution.objects.create(
            slug=validated_data["slug"],
            name=validated_data["name"],
            is_active=True,
        )


class SuperadminCreateAdminSerializer(serializers.Serializer):
    """Superadmin provisions a tenant admin. The target institution is looked
    up by slug from the body (cross-tenant) — unlike AdminCreateUserSerializer,
    which pins the tenant to the caller's own JWT claim."""

    institution_slug = serializers.SlugField()
    email = serializers.EmailField()
    user_code = serializers.RegexField(r"^[A-Za-z0-9_-]{1,30}$")
    password = serializers.CharField(
        write_only=True, min_length=8, style={"input_type": "password"}
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
        if institution and User.objects.filter(
            tenant=institution, user_code=attrs["user_code"]
        ).exists():
            raise serializers.ValidationError(
                {"user_code": "A user with this user_code already exists."}
            )
        attrs["email"] = email
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(
            tenant=self._institution,
            email=validated_data["email"],
            password=validated_data["password"],
            role=User.Role.ADMIN,
            user_code=validated_data["user_code"],
        )


class LoginSerializer(serializers.Serializer):
    institution_slug = serializers.SlugField()
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class MeSerializer(serializers.Serializer):
    user_code = serializers.CharField(allow_null=True)
    email = serializers.EmailField()
    role = serializers.CharField()
    tenant = serializers.CharField()


class UserProfileSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.CharField(max_length=20, required=False, allow_blank=True)
    emergency_contact_name = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    emergency_contact_phone = serializers.CharField(
        max_length=20, required=False, allow_blank=True
    )
    blood_group = serializers.CharField(max_length=5, required=False, allow_blank=True)
    profile_photo_url = serializers.URLField(required=False, allow_blank=True)
    updated_at = serializers.DateTimeField(read_only=True)
