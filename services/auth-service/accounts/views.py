"""Register / login / refresh / me endpoints.

Access tokens are built manually (``RefreshToken.for_user`` + explicit claim
assignment) rather than via ``TokenObtainPairSerializer.get_token`` so that
authentication can go through the tenant-scoped ``TenantAuthBackend`` (email
alone is not enough to identify a user — see ``accounts/backends.py``) before
any token is minted. The claim keys (``sub``, ``role``, ``tenant``) are
exactly what ``suerp_common.auth.JWTAuthentication`` reads; every other
service treats this shape as its contract with auth-service.
"""

from accounts.models import Institution, LoginAudit, User, UserProfile
from accounts.serializers import (
    AdminCreateUserSerializer,
    BulkCreateStudentRowSerializer,
    InstitutionCreateSerializer,
    InstitutionSerializer,
    LoginSerializer,
    MeSerializer,
    RefreshSerializer,
    RegisterSerializer,
    SuperadminCreateAdminSerializer,
    UserByCodeSerializer,
    UserListSerializer,
    UserProfileSerializer,
)
from django.conf import settings
from django.contrib.auth import authenticate
from django.db import transaction
from django.db.utils import OperationalError
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
    refresh["sub"] = user.user_code
    refresh["role"] = user.role
    refresh["tenant"] = str(user.tenant_id)

    access = refresh.access_token
    access["sub"] = user.user_code
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
                payload={"user_code": user.user_code, "role": user.role},
            )

        return ok(
            {"user_code": user.user_code, "email": user.email, "role": user.role},
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
                "user_code": user.user_code,
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
        qs = User.objects.filter(tenant_id=self.request.user.tenant_id).order_by("date_joined")
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")
        return qs

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
                payload={"user_code": user.user_code, "role": user.role},
            )

        return ok(
            {"user_code": user.user_code, "email": user.email, "role": user.role},
            message="User created.",
            status=201,
        )


class UserBulkCreateView(APIView):
    """POST /api/v1/auth/users/bulk/ — admin bulk-creates students.

    Every row becomes role=student (no per-row role field — this endpoint is
    student-only by design). Each row is validated and saved in its OWN
    transaction.atomic(), so one bad row (duplicate email/user_code, either
    against the DB or against an earlier row in this same upload) does not
    abort the rest of the batch — matches the partial-failure contract used
    by hostel-service's bulk allocation import.

    department/batch/semester ride along in the user.registered payload
    purely for student-service's consumer to pick up (see
    students/consumers.py) — auth-service does not otherwise use them.
    """

    permission_classes = [role_required("admin")]

    def post(self, request):
        rows = request.data.get("rows")
        if not isinstance(rows, list) or len(rows) == 0:
            return fail("Request must include a non-empty 'rows' list.", status=400)

        try:
            institution = Institution.objects.get(pk=request.user.tenant_id)
        except Institution.DoesNotExist:
            return fail("Institution no longer exists.", status=404)

        created = []
        failed = []
        seen_emails: set[str] = set()
        seen_user_codes: set[str] = set()

        for index, row in enumerate(rows):
            serializer = BulkCreateStudentRowSerializer(
                data=row,
                context={
                    "institution": institution,
                    "seen_emails": seen_emails,
                    "seen_user_codes": seen_user_codes,
                },
            )
            if not serializer.is_valid():
                failed.append(
                    {
                        "row": index,
                        "email": row.get("email", "") if isinstance(row, dict) else "",
                        "error": _first_error_message(serializer.errors),
                    }
                )
                continue

            with transaction.atomic():
                user = serializer.save()
                publish_event(
                    "user.registered",
                    tenant_id=str(user.tenant_id),
                    payload={
                        "user_code": user.user_code,
                        "role": user.role,
                        "department": serializer.validated_data["department"],
                        "batch": serializer.validated_data["batch"],
                        "semester": serializer.validated_data["semester"],
                    },
                )
            seen_emails.add(user.email)
            seen_user_codes.add(user.user_code)
            created.append({"row": index, "email": user.email, "user_code": user.user_code})

        return ok(
            {"created": created, "failed": failed},
            message=f"{len(created)} student(s) created, {len(failed)} failed.",
            status=201,
        )


def _first_error_message(errors: dict) -> str:
    """Flatten a DRF errors dict down to one human-readable string for a
    bulk-row failure entry (the UI shows one error string per failed row,
    not a nested field-by-field structure)."""
    for value in errors.values():
        if isinstance(value, list) and value:
            return str(value[0])
        return str(value)
    return "Invalid row."


class UserBulkDeactivateView(APIView):
    """POST /api/v1/auth/users/bulk-delete/ — admin bulk soft-delete.

    Soft-delete only (``is_active = False``) — other services hold this
    user's ``user_code`` as a loose string reference with no real FK (each
    service owns its own database), so a hard delete would silently orphan
    rows in student-service/hostel-service/finance-service/etc. Setting
    is_active=False keeps the row (and every cross-service reference to it)
    intact while blocking login (see LoginView/TenantAuthBackend).

    Each user_code is processed independently — one bad entry (unknown
    code, self-delete, last-admin) does not abort the rest of the batch,
    matching UserBulkCreateView's partial-failure contract.
    """

    permission_classes = [role_required("admin")]

    def post(self, request):
        user_codes = request.data.get("user_codes")
        if not isinstance(user_codes, list) or len(user_codes) == 0:
            return fail("Request must include a non-empty 'user_codes' list.", status=400)

        tenant_id = request.user.tenant_id
        caller_code = request.user.id

        deactivated = []
        failed = []

        for user_code in user_codes:
            try:
                with transaction.atomic():
                    user = User.objects.select_for_update().get(pk=user_code, tenant_id=tenant_id)

                    if user.user_code == caller_code:
                        failed.append(
                            {
                                "user_code": user_code,
                                "error": "Cannot deactivate your own account.",
                            }
                        )
                        continue

                    if user.role == User.Role.ADMIN and user.is_active:
                        # select_for_update() here (not a plain read) closes a
                        # TOCTOU race: without it, two concurrent requests each
                        # deactivating a DIFFERENT admin in the same tenant could
                        # both see the other as still active, both pass this
                        # guard, and both commit — leaving zero active admins.
                        # Locking every active-admin row means a second
                        # transaction targeting a different admin blocks here
                        # until the first commits/rolls back, then re-reads the
                        # up-to-date count. Postgres-only guarantee (see
                        # infra/docker-compose.yml, .github/workflows/ci.yml);
                        # SQLite ignores FOR UPDATE, an existing limitation.
                        other_active_admins = (
                            User.objects.select_for_update()
                            .filter(tenant_id=tenant_id, role=User.Role.ADMIN, is_active=True)
                            .exclude(pk=user.pk)
                        )
                        if not other_active_admins.exists():
                            failed.append(
                                {
                                    "user_code": user_code,
                                    "error": "Cannot deactivate the last active admin.",
                                }
                            )
                            continue

                    user.is_active = False
                    user.save(update_fields=["is_active"])
                    publish_event(
                        "user.deactivated",
                        tenant_id=str(tenant_id),
                        payload={"user_code": user.user_code, "role": user.role},
                    )
            except User.DoesNotExist:
                failed.append({"user_code": user_code, "error": "User not found."})
                continue
            except OperationalError:
                # Postgres's deadlock detector can abort this transaction
                # when two concurrent requests each lock their own target
                # row first and then need the OTHER request's target row
                # via the other_active_admins lock above — a circular wait.
                # Surface it as a per-row failure instead of a 500 so the
                # rest of the batch still gets a clean partial result.
                failed.append(
                    {
                        "user_code": user_code,
                        "error": "Could not process due to a concurrent update; please retry.",
                    }
                )
                continue

            deactivated.append({"user_code": user.user_code, "email": user.email})

        return ok(
            {"deactivated": deactivated, "failed": failed},
            message=f"{len(deactivated)} user(s) deactivated, {len(failed)} failed.",
        )


class UserByCodeView(APIView):
    """GET /api/v1/auth/users/by-code/?user_code=... — resolve a user_code to
    its User row within the caller's own tenant.

    This is the platform's single identity-resolution endpoint: every
    student_user_code/warden_id elsewhere IS this user_code (see docs/
    superpowers/specs/2026-07-07-user-code-profile-design.md), so
    hostel-service calls this endpoint (through the gateway, forwarding the
    caller's own token) to validate a warden/student-typed user_code before
    storing it on its own Allocation/Block rows.
    """

    permission_classes = [role_required("warden", "admin")]

    def get(self, request):
        user_code = request.query_params.get("user_code", "").strip()
        if not user_code:
            return fail("Query parameter 'user_code' is required.", status=400)

        try:
            user = User.objects.get(tenant_id=request.user.tenant_id, user_code=user_code)
        except User.DoesNotExist:
            return fail(f"No user found with user_code {user_code}.", status=404)

        return ok(
            UserByCodeSerializer(
                {"user_code": user.user_code, "email": user.email, "role": user.role}
            ).data
        )


class MyProfileView(APIView):
    """GET/PATCH /api/v1/auth/users/me/profile/ — the caller's own profile.

    Superadmin has no UserProfile row (excluded by design) — always 403.
    """

    permission_classes = [IsAuthenticated]

    def _get_user(self, request):
        try:
            return User.objects.get(pk=request.user.id)
        except User.DoesNotExist:
            return None

    def get(self, request):
        user = self._get_user(request)
        if user is None:
            return fail("User no longer exists.", status=401)
        if user.role == User.Role.SUPERADMIN:
            return fail("Superadmin has no profile.", status=403)

        profile, _ = UserProfile.objects.get_or_create(user=user)
        return ok(UserProfileSerializer(profile).data)

    def patch(self, request):
        user = self._get_user(request)
        if user is None:
            return fail("User no longer exists.", status=401)
        if user.role == User.Role.SUPERADMIN:
            return fail("Superadmin has no profile.", status=403)

        profile, _ = UserProfile.objects.get_or_create(user=user)
        serializer = UserProfileSerializer(profile, data=request.data, partial=True)
        if not serializer.is_valid():
            return fail("Invalid profile payload.", errors=serializer.errors, status=400)

        for field, value in serializer.validated_data.items():
            setattr(profile, field, value)
        profile.save()
        return ok(UserProfileSerializer(profile).data, message="Profile updated.")


class UserProfileView(APIView):
    """GET /api/v1/auth/users/{user_code}/profile/ — admin/warden view of
    another user's profile (read-only), within the caller's own tenant.
    """

    permission_classes = [role_required("warden", "admin")]

    def get(self, request, user_code):
        try:
            user = User.objects.get(tenant_id=request.user.tenant_id, user_code=user_code)
        except User.DoesNotExist:
            return fail("User not found.", status=404)
        if user.role == User.Role.SUPERADMIN:
            return fail("Superadmin has no profile.", status=403)

        profile, _ = UserProfile.objects.get_or_create(user=user)
        return ok(UserProfileSerializer(profile).data)


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
                payload={"user_code": user.user_code, "role": user.role},
            )

        return ok(
            {
                "user_code": user.user_code,
                "email": user.email,
                "role": user.role,
                "institution_slug": user.tenant.slug,
            },
            message="Admin created.",
            status=201,
        )
