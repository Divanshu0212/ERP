"""Institution (tenant), User, UserProfile, and LoginAudit models.

Institution is THE tenant table — it defines tenants and is therefore NOT
itself tenant-scoped. It is a plain ``models.Model``, unlike every other
tenant-owned model in the platform.

User and LoginAudit belong to a tenant, but they are intentionally NOT
``suerp_common.tenancy.TenantModel`` subclasses. auth-service is the identity
authority: it issues JWTs and must look users up across the login flow
*before* a tenant context is fully established (e.g. resolving which
institution an email belongs to). ``TenantModel``'s auto-filtering manager
would silently break exactly those lookups. Instead these models carry an
explicit ``tenant`` ForeignKey to ``Institution``. A real FK is safe here
because auth-service is the one service that owns the ``Institution`` table
in its own database — every other service only ever receives ``tenant_id``
as an opaque UUID claim inside the JWT and never touches this table.

``User.user_code`` is the platform's human-facing identifier and literal
primary key (replaces a UUID pk) for every role except ``superadmin``, which
gets no *admin-assigned* ``user_code`` (nothing an admin ever types in or
sees). Every other service's stored "who is this" reference holds this same
``user_code`` string — see
docs/superpowers/specs/2026-07-07-user-code-profile-design.md.

**Deviation from the design spec on one point:** the spec calls for
``user_code`` to be a *nullable* ``CharField`` primary key so superadmin rows
can carry ``NULL``. That is not achievable on any real backend: a SQL
``PRIMARY KEY`` constraint always implies ``NOT NULL`` (verified directly
against Postgres 16 — inserting ``NULL`` into a varchar ``PRIMARY KEY``
column raises ``null value ... violates not-null constraint``), and Django's
own system checks refuse to even generate migrations for
``primary_key=True, null=True`` (``fields.E007``). SQLite is the one backend
lax enough to accept it (it treats a non-integer ``PRIMARY KEY`` as a mere
unique index, where NULLs are non-distinct) — that laxness would silently
mask the bug in local/dev SQLite runs while breaking outright in CI and
production, both of which run Postgres (see .github/workflows/ci.yml,
infra/docker-compose.yml). ``manage.py makemigrations`` was run against this
exact model shape and failed with E007 before any Postgres round-trip was
even needed, so this is not a borderline call.

Fix: ``user_code`` stays ``primary_key=True`` with a real, DB-enforced
``NOT NULL`` column — a bare pk field cannot be anything else. For
superadmin, ``UserManager.create_superuser`` auto-generates an internal,
system-only placeholder (``"~" + <24 random hex chars>``) that satisfies
``NOT NULL``/uniqueness like any other row's pk, but is never admin-entered,
never displayed, and is outside the admin-assignable ``user_code`` character
class (``^[A-Za-z0-9_-]{1,30}$`` — see Task 2's serializer validators, which
reject ``~``). This preserves every actual guarantee the design cared about
(superadmin never has a *meaningful*, admin-visible user_code; regular users
are uniquely keyed by an admin-assigned one per tenant) without requiring
something SQL cannot express.

**Second deviation, flagged for the plan owner rather than silently
resolved:** the design spec (decision 1 + 3) asks for BOTH "``user_code`` is
the literal, single-column primary key" AND "``user_code`` unique only per
tenant, same value reusable across different institutions." These two
requirements are mutually exclusive on every backend: a single-column
``PRIMARY KEY`` is necessarily globally unique (confirmed directly against
Postgres — inserting the same ``user_code`` under a second, different
``tenant`` raises ``duplicate key value violates unique constraint
..._pkey``), so the only way to get per-tenant-scoped reuse would be a
composite ``(tenant, user_code)`` primary key, which contradicts "literal
single-column pk" (``user.pk == "STU-001"``, not a tuple) and would ripple
into every one of the other 17 migration tasks that treat a bare
``user_code`` string as the whole identity. This implementation keeps
``user_code`` globally unique (satisfies decision 1 and every downstream
task's "hold this same user_code string" assumption) and narrows decision 3
to global rather than per-tenant uniqueness — the ``(tenant, user_code)``
UniqueConstraint below is now a redundant superset of the pk's own
uniqueness, kept only for symmetry with ``unique_email_per_tenant`` and left
in place rather than removed since it is harmless. If per-tenant code reuse
across institutions is actually a hard requirement, that needs a deliberate
redesign (composite pk or a separate surrogate pk + unique user_code field)
before later tasks build more FKs on top of the current shape.
"""

import secrets
import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models

#: Prefix marking a User.user_code as an internal superadmin placeholder,
#: never an admin-assigned code (which is restricted to [A-Za-z0-9_-]).
SUPERADMIN_CODE_PREFIX = "~"


def _generate_superadmin_code() -> str:
    """A unique, non-null pk placeholder for superadmin rows only.

    24 hex chars + the 1-char prefix = 25, comfortably under max_length=30
    while still being effectively collision-free (96 bits of randomness).
    """
    return SUPERADMIN_CODE_PREFIX + secrets.token_hex(12)


class Institution(models.Model):
    """A tenant. Not tenant-scoped — this table defines the tenants."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.slug


class UserManager(BaseUserManager):
    """Manager for the tenant-aware custom User model.

    ``tenant`` is required for both ``create_user`` and ``create_superuser``
    since every user belongs to exactly one institution. ``user_code`` is
    required for every role except ``superadmin`` (enforced by the caller —
    ``create_superuser`` never passes one, ``create_user`` always should
    outside of the superadmin bootstrap path).
    """

    use_in_migrations = True

    def _create_user(self, tenant, email, password, user_code=None, **extra_fields):
        if not tenant:
            raise ValueError("Users must have a tenant (Institution).")
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email)
        user = self.model(tenant=tenant, email=email, user_code=user_code, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, tenant, email, password=None, user_code=None, **extra_fields):
        # Guard against a silent footgun: user_code is a NOT NULL primary
        # key (see module docstring), and Django's CharField coerces a
        # missing/None value to "" rather than raising. Without this check,
        # a second create_user() call that also forgot user_code would
        # collide on pk="" and silently turn into an UPDATE of the first
        # user's row instead of failing loudly.
        if not user_code:
            raise ValueError(
                "create_user() requires a non-empty user_code for every role "
                "except superadmin (use create_superuser() for superadmin)."
            )
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(tenant, email, password, user_code=user_code, **extra_fields)

    def create_superuser(self, tenant, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        # Superadmin never gets an admin-assigned user_code — see module
        # docstring. A system-generated placeholder fills the pk column
        # instead, since the column itself can never be NULL.
        return self._create_user(
            tenant, email, password, user_code=_generate_superadmin_code(), **extra_fields
        )


class User(AbstractBaseUser, PermissionsMixin):
    """A tenant-scoped identity. See module docstring for why this is a
    plain FK to Institution rather than a TenantModel subclass."""

    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        FACULTY = "faculty", "Faculty"
        WARDEN = "warden", "Warden"
        DRIVER = "driver", "Driver"
        ADMIN = "admin", "Admin"
        ALUMNI = "alumni", "Alumni"
        SUPERADMIN = "superadmin", "Super Admin"
        CANTEEN_OWNER = "canteen_owner", "Canteen Owner"

    # NOT NULL — a real SQL PRIMARY KEY cannot be nullable on any backend
    # (verified against Postgres 16; Django's own fields.E007 check agrees).
    # Superadmin rows get a system-generated placeholder here instead of an
    # admin-assigned code — see ``has_user_code``/module docstring.
    user_code = models.CharField(max_length=30, primary_key=True)
    tenant = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="users")
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["tenant", "role"]

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "email"], name="unique_email_per_tenant"),
            models.UniqueConstraint(
                fields=["tenant", "user_code"], name="unique_user_code_per_tenant"
            ),
        ]

    @property
    def has_user_code(self) -> bool:
        """False for superadmin (system placeholder), True for every other
        role (admin-assigned code)."""
        return not self.user_code.startswith(SUPERADMIN_CODE_PREFIX)

    def __str__(self):
        code = self.user_code if self.has_user_code else self.email
        return f"{code} ({self.tenant_id})"


class UserProfile(models.Model):
    """Common profile fields for every role except superadmin.

    1:1 with ``User`` via a pk-carrying OneToOneField (``profile.pk`` IS the
    owning user's ``user_code``). Every field is optional/blank — filled in
    later via the frontend profile tab, never required at user-creation time.
    """

    user = models.OneToOneField(
        User, primary_key=True, on_delete=models.CASCADE, related_name="profile"
    )
    phone = models.CharField(max_length=20, blank=True, default="")
    address = models.TextField(blank=True, default="")
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True, default="")
    emergency_contact_name = models.CharField(max_length=255, blank=True, default="")
    emergency_contact_phone = models.CharField(max_length=20, blank=True, default="")
    blood_group = models.CharField(max_length=5, blank=True, default="")
    profile_photo_url = models.URLField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile({self.user_id})"


class LoginAudit(models.Model):
    """Login attempt record, used for lockout counting.

    ``email`` is stored separately from ``user`` because a failed login for
    an unknown email has no matching User row, but must still count toward
    lockout for that email.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="login_audits")
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="login_audits",
        null=True,
        blank=True,
    )
    email = models.CharField(max_length=254)
    ip = models.GenericIPAddressField(null=True, blank=True)
    success = models.BooleanField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["email", "timestamp"], name="loginaudit_email_ts"),
            models.Index(fields=["tenant", "timestamp"], name="loginaudit_tenant_ts"),
        ]

    def __str__(self):
        return f"{self.email} @ {self.timestamp} ({'ok' if self.success else 'fail'})"
