"""Institution (tenant), User, and LoginAudit models.

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
"""

import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


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
    since every user belongs to exactly one institution.
    """

    use_in_migrations = True

    def _create_user(self, tenant, email, password, **extra_fields):
        if not tenant:
            raise ValueError("Users must have a tenant (Institution).")
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email)
        user = self.model(tenant=tenant, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, tenant, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(tenant, email, password, **extra_fields)

    def create_superuser(self, tenant, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(tenant, email, password, **extra_fields)


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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
            models.UniqueConstraint(fields=["tenant", "email"], name="unique_email_per_tenant")
        ]

    def __str__(self):
        return f"{self.email} ({self.tenant_id})"


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
