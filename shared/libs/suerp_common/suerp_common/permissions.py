"""Reusable DRF permission classes.

All authorization decisions read from the verified JWT principal
(``request.user`` produced by :class:`suerp_common.auth.JWTAuthentication`) and
from the active tenant context — never from request headers.
"""

from rest_framework.permissions import BasePermission

from .tenancy import get_current_tenant

# Roles with unconditional cross-object access within their tenant.
_PRIVILEGED_ROLES = {"admin"}


def role_required(*roles: str) -> type[BasePermission]:
    """Build a permission class allowing only the given roles.

    Usage: ``permission_classes = [role_required("warden", "admin")]``.
    """

    allowed = set(roles)

    class _RolePermission(BasePermission):
        def has_permission(self, request, view):
            user = getattr(request, "user", None)
            return bool(user and user.is_authenticated and getattr(user, "role", None) in allowed)

    _RolePermission.__name__ = "RoleRequired_" + "_".join(sorted(allowed))
    return _RolePermission


class TenantRequired(BasePermission):
    """Deny any request that has no resolved tenant context.

    Backstop against a missing/misconfigured token reaching tenant-scoped data.
    """

    def has_permission(self, request, view):
        return get_current_tenant() is not None


class IsObjectOwner(BasePermission):
    """Object-level: the acting user owns the object, or is privileged.

    Objects expose ownership via an ``owner_id`` attribute (or ``student_id`` /
    ``user_id`` / ``user_code`` as fallbacks used across services).
    """

    owner_fields = ("owner_id", "student_id", "user_id", "user_code", "raised_by")

    def has_object_permission(self, request, view, obj):
        user = getattr(request, "user", None)
        if not (user and user.is_authenticated):
            return False
        if getattr(user, "role", None) in _PRIVILEGED_ROLES:
            return True
        for field in self.owner_fields:
            if hasattr(obj, field):
                return str(getattr(obj, field)) == str(user.id)
        return False
