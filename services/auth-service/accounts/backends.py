"""Tenant-aware authentication backend.

``accounts.User`` is unique on ``(tenant, email)``, not on ``email`` alone —
the same email can belong to different people at different institutions.
Stock ``django.contrib.auth.backends.ModelBackend`` authenticates by
``USERNAME_FIELD`` alone (a global ``.get(email=...)`` lookup), which would
silently authenticate against the wrong tenant's user. ``TenantAuthBackend``
requires an explicit ``tenant`` and scopes the lookup to it.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

UserModel = get_user_model()


class TenantAuthBackend(ModelBackend):
    """Authenticate a user by (tenant, email, password) instead of email alone."""

    def authenticate(self, request, email=None, password=None, tenant=None, **kwargs):
        if email is None or password is None or tenant is None:
            return None

        try:
            user = UserModel.objects.get(
                tenant=tenant, email=UserModel.objects.normalize_email(email)
            )
        except UserModel.DoesNotExist:
            # Run the hasher anyway to keep timing consistent whether or not
            # the email exists, mirroring ModelBackend's own behavior.
            UserModel().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
