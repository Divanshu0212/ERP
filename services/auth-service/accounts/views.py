"""Register / login / refresh / me endpoints.

Access tokens are built manually (``RefreshToken.for_user`` + explicit claim
assignment) rather than via ``TokenObtainPairSerializer.get_token`` so that
authentication can go through the tenant-scoped ``TenantAuthBackend`` (email
alone is not enough to identify a user — see ``accounts/backends.py``) before
any token is minted. The claim keys (``sub``, ``role``, ``tenant``) are
exactly what ``suerp_common.auth.JWTAuthentication`` reads; every other
service treats this shape as its contract with auth-service.
"""

from accounts.models import Institution, LoginAudit, User
from accounts.serializers import (
    AdminCreateUserSerializer,
    InstitutionCreateSerializer,
    InstitutionSerializer,
    LoginSerializer,
    MeSerializer,
    RefreshSerializer,
    RegisterSerializer,
    SuperadminCreateAdminSerializer,
    UserByEmailSerializer,
    UserListSerializer,
)
from django.conf import settings
from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from suerp_common.envelope import fail, ok
from suerp_common.outbox import publish_event
from suerp_common.permissions import role_required

LOCKOUT_THRESHOLD = 5
LOCKOUT_WINDOW_MINUTES = 15


def _issue_tokens(user: User) -> dict:
    """Mint a refresh+access token pair carrying sub/role/tenant claims."""
    refresh = RefreshToken.for_user(user)
    refresh["sub"] = str(user.id)
    refresh["role"] = user.role
    refresh["tenant"] = str(user.tenant_id)

    access = refresh.access_token
    access["sub"] = str(user.id)
    access["role"] = user.role
    access["tenant"] = str(user.tenant_id)

    return {"access": str(access), "refresh": str(refresh)}


def _resolve_active_institution(slug: str) -> Institution | None:
    try:
        institution = Institution.objects.get(slug=slug)
    except Institution.DoesNotExist:
        return None
    if not institution.is_active:
        return None
    return institution


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Registration failed.", errors=serializer.errors, status=400)

        # User creation and the user.registered outbox row MUST commit or
        # roll back together — this is the transactional-outbox guarantee.
        # publish_event only ever inserts a row (never touches the broker),
        # so nothing here talks to RabbitMQ; drain_outbox_task relays it later.
        with transaction.atomic():
            user = serializer.save()
            publish_event(
                "user.registered",
                tenant_id=str(user.tenant_id),
                payload={"user_id": str(user.id), "role": user.role},
            )

        return ok(
            {"id": str(user.id), "email": user.email, "role": user.role},
            message="Registered.",
            status=201,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid login request.", errors=serializer.errors, status=400)

        slug = serializer.validated_data["institution_slug"]
        email = User.objects.normalize_email(serializer.validated_data["email"])
        password = serializer.validated_data["password"]

        institution = _resolve_active_institution(slug)
        if institution is None:
            return fail("Unknown or inactive institution.", status=400)

        ip = request.META.get("REMOTE_ADDR")

        if self._is_locked_out(institution, email):
            return fail(
                "Too many failed login attempts. Try again later.",
                status=429,
            )

        user = authenticate(request, email=email, password=password, tenant=institution)

        if user is None:
            LoginAudit.objects.create(
                tenant=institution, user=None, email=email, ip=ip, success=False
            )
            return fail("Invalid credentials.", status=401)

        LoginAudit.objects.create(tenant=institution, user=user, email=email, ip=ip, success=True)

        tokens = _issue_tokens(user)
        return ok(tokens, message="Login successful.")

    @staticmethod
    def _is_locked_out(institution: Institution, email: str) -> bool:
        window_start = timezone.now() - timezone.timedelta(minutes=LOCKOUT_WINDOW_MINUTES)
        failure_count = LoginAudit.objects.filter(
            tenant=institution,
            email=email,
            success=False,
            timestamp__gte=window_start,
        ).count()
        return failure_count >= LOCKOUT_THRESHOLD


class RefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid refresh request.", errors=serializer.errors, status=400)

        try:
            refresh = RefreshToken(serializer.validated_data["refresh"])
        except TokenError as exc:
            return fail(f"Invalid or expired refresh token: {exc}", status=401)

        access = refresh.access_token
        # RefreshToken.access_token copies claims automatically except those
        # listed in no_copy_claims (token_type/exp/iat/jti) — sub/role/tenant
        # ride along already, but set explicitly to guarantee the contract
        # even if SimpleJWT's copy behavior changes upstream.
        access["sub"] = refresh.get("sub")
        access["role"] = refresh.get("role")
        access["tenant"] = refresh.get("tenant")

        data = {"access": str(access)}

        if settings.SIMPLE_JWT.get("ROTATE_REFRESH_TOKENS"):
            refresh.set_jti()
            refresh.set_exp()
            refresh.set_iat()
            data["refresh"] = str(refresh)

        return ok(data, message="Token refreshed.")


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # request.user is suerp_common.auth.SimpleUser, built from verified
        # JWT claims only (zero-trust: no DB lookup needed for identity), but
        # /me additionally confirms the user still exists and is active.
        try:
            user = User.objects.get(pk=request.user.id)
        except User.DoesNotExist:
            return fail("User no longer exists.", status=401)

        serializer = MeSerializer(
            {
                "id": user.id,
                "email": user.email,
                "role": user.role,
                "tenant": str(user.tenant_id),
            }
        )
        return ok(serializer.data)


class InstitutionView(APIView):
    """Return the caller's own institution, resolved from the JWT tenant claim."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            institution = Institution.objects.get(pk=request.user.tenant_id)
        except Institution.DoesNotExist:
            return fail("Institution no longer exists.", status=404)
        return ok(InstitutionSerializer(institution).data)


class UserAdminView(ListAPIView):
    """Admin-only management of the caller's tenant users.

    GET lists the tenant's users (paginated); POST creates a user in the
    admin's own institution. ``User.objects`` is NOT tenant-scoped (auth-service
    owns identity and must query across tenants during login), so the tenant
    filter here is explicit — the admin's tenant comes from their verified JWT
    claim, never from the request body.
    """

    permission_classes = [role_required("admin")]
    serializer_class = UserListSerializer

    def get_queryset(self):
        return User.objects.filter(tenant_id=self.request.user.tenant_id).order_by("date_joined")

    def post(self, request):
        try:
            institution = Institution.objects.get(pk=request.user.tenant_id)
        except Institution.DoesNotExist:
            return fail("Institution no longer exists.", status=404)

        serializer = AdminCreateUserSerializer(
            data=request.data, context={"institution": institution}
        )
        if not serializer.is_valid():
            return fail("User creation failed.", errors=serializer.errors, status=400)

        # User row and its user.registered outbox event commit or roll back
        # together — the transactional-outbox guarantee (see RegisterView).
        with transaction.atomic():
            user = serializer.save()
            publish_event(
                "user.registered",
                tenant_id=str(user.tenant_id),
                payload={"user_id": str(user.id), "role": user.role},
            )

        return ok(
            {"id": str(user.id), "email": user.email, "role": user.role},
            message="User created.",
            status=201,
        )


class UserByEmailView(APIView):
    """GET /api/v1/auth/users/by-email/?email=... — resolve an email to its
    User.id within the caller's own tenant.

    This is the platform's single identity-resolution endpoint: every
    student_id/warden_id elsewhere IS this User.id (see docs/superpowers/
    specs/2026-07-04-allocation-email-bulk-import-design.md), so
    hostel-service calls this endpoint (through the gateway, forwarding the
    caller's own token) to turn a warden-typed email into the UUID its
    Allocation/Block rows actually store.
    """

    permission_classes = [role_required("warden", "admin")]

    def get(self, request):
        email = request.query_params.get("email", "").strip()
        if not email:
            return fail("Query parameter 'email' is required.", status=400)

        email = User.objects.normalize_email(email)
        try:
            user = User.objects.get(tenant_id=request.user.tenant_id, email__iexact=email)
        except User.DoesNotExist:
            return fail(f"No user found with email {email}.", status=404)

        return ok(
            UserByEmailSerializer({"id": user.id, "email": user.email, "role": user.role}).data
        )


PLATFORM_SLUG = "platform"


class PlatformInstitutionView(ListAPIView):
    """Platform-superadmin management of institutions (tenants), CROSS-tenant.

    Unlike every other endpoint in this service these are deliberately NOT
    tenant-filtered: the superadmin operates across all institutions. GET lists
    every institution (newest first) except the operator-internal ``platform``
    tenant; POST creates a new institution.
    """

    permission_classes = [role_required("superadmin")]
    serializer_class = InstitutionSerializer

    def get_queryset(self):
        return Institution.objects.exclude(slug=PLATFORM_SLUG).order_by("-created_at")

    def post(self, request):
        serializer = InstitutionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Institution creation failed.", errors=serializer.errors, status=400)

        institution = serializer.save()
        return ok(
            {
                "id": str(institution.id),
                "slug": institution.slug,
                "name": institution.name,
                "is_active": institution.is_active,
            },
            message="Institution created.",
            status=201,
        )


class PlatformAdminView(APIView):
    """Platform-superadmin provisioning of a tenant admin, CROSS-tenant.

    Creates a role=admin User in the TARGET institution (looked up by slug in
    the body), and emits the user.registered outbox event in the same
    transaction (see RegisterView for the transactional-outbox guarantee).
    """

    permission_classes = [role_required("superadmin")]

    def post(self, request):
        serializer = SuperadminCreateAdminSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Admin creation failed.", errors=serializer.errors, status=400)

        with transaction.atomic():
            user = serializer.save()
            publish_event(
                "user.registered",
                tenant_id=str(user.tenant_id),
                payload={"user_id": str(user.id), "role": user.role},
            )

        return ok(
            {
                "id": str(user.id),
                "email": user.email,
                "role": user.role,
                "institution_slug": user.tenant.slug,
            },
            message="Admin created.",
            status=201,
        )
