"""Issue, rotate, and revoke device-bound refresh chains.

Pure functions over the models — no HTTP, no DRF. ``accounts/views.py`` is
the only caller. Keeping the chain logic here means the reuse-detection
rule lives in exactly one place and can be tested without a request.

The claim shape (``sub``/``role``/``tenant``) mirrors ``views._issue_tokens``
because every other service reads exactly those keys via
``suerp_common.auth.JWTAuthentication``.
"""

from datetime import UTC, datetime

from accounts.models import Device, RefreshTokenRecord, User
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken


class TokenInvalidError(Exception):
    """The presented refresh token is malformed, expired, or unknown."""


class TokenReuseError(Exception):
    """A refresh token that was already rotated was presented again.

    Treated as theft: the entire device chain is revoked before raising.
    """


def _stamp_claims(token, user: User) -> None:
    token["sub"] = user.user_code
    token["role"] = user.role
    token["tenant"] = str(user.tenant_id)


def register_device(
    user: User,
    device_id: str,
    platform: str,
    model_name: str = "",
    push_token: str = "",
) -> Device:
    """Create or refresh the caller's device row. Idempotent per device_id."""
    device, created = Device.objects.get_or_create(
        user=user,
        device_id=device_id,
        defaults={
            "tenant_id": user.tenant_id,
            "platform": platform,
            "model_name": model_name,
            "push_token": push_token,
        },
    )
    if not created:
        device.platform = platform
        device.model_name = model_name
        if push_token:
            device.push_token = push_token
        device.is_stale = False
        device.save(update_fields=["platform", "model_name", "push_token", "is_stale"])
    return device


def issue_for_device(user: User, device: Device) -> dict:
    """Mint a fresh access+refresh pair and record the refresh token."""
    refresh = RefreshToken.for_user(user)
    _stamp_claims(refresh, user)

    access = refresh.access_token
    _stamp_claims(access, user)

    RefreshTokenRecord.objects.create(
        tenant_id=user.tenant_id,
        user=user,
        device=device,
        jti=refresh["jti"],
        expires_at=datetime.fromtimestamp(refresh["exp"], tz=UTC),
    )

    return {"access": str(access), "refresh": str(refresh)}


def _revoke(records) -> int:
    return records.update(revoked_at=timezone.now())


def revoke_device_chain(device: Device) -> int:
    """Revoke every live refresh token issued to this device."""
    return _revoke(RefreshTokenRecord.objects.filter(device=device, revoked_at__isnull=True))


def rotate(raw_refresh: str) -> dict:
    """Exchange a refresh token for a new pair, revoking the presented one.

    Presenting a token that was already rotated (``replaced_by`` is set) means
    two parties hold the same token — the legitimate client and whoever
    captured it. There is no way to tell which is which, so the whole device
    chain dies and both are forced to re-authenticate.

    The reuse revocation happens here, OUTSIDE the rotation transaction:
    raising out of an ``atomic`` block rolls it back, which would undo the
    very revocation the reuse is supposed to trigger.
    """
    try:
        return _rotate_chain(raw_refresh)
    except _ReuseDetected as exc:
        revoke_device_chain(exc.device)
        raise TokenReuseError("Refresh token was already used; device chain revoked.") from None


class _ReuseDetected(Exception):
    """Internal signal: rotation aborted because the token was already used."""

    def __init__(self, device: Device):
        super().__init__("reuse")
        self.device = device


@transaction.atomic
def _rotate_chain(raw_refresh: str) -> dict:
    try:
        token = RefreshToken(raw_refresh)
    except TokenError as exc:
        raise TokenInvalidError(str(exc)) from exc

    try:
        record = RefreshTokenRecord.objects.select_for_update().get(jti=token["jti"])
    except RefreshTokenRecord.DoesNotExist as exc:
        raise TokenInvalidError("Unknown refresh token.") from exc

    if record.replaced_by_id is not None:
        # Signal only — the caller revokes once this transaction has unwound.
        raise _ReuseDetected(record.device)

    if not record.is_live:
        raise TokenInvalidError("Refresh token is revoked or expired.")

    user = record.user
    if not user.is_active:
        raise TokenInvalidError("User is inactive.")

    tokens = issue_for_device(user, record.device)

    successor = RefreshTokenRecord.objects.get(jti=RefreshToken(tokens["refresh"])["jti"])
    record.revoked_at = timezone.now()
    record.replaced_by = successor
    record.save(update_fields=["revoked_at", "replaced_by"])

    return tokens
