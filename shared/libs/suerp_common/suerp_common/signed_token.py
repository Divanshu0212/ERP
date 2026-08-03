"""Short-lived signed capability tokens.

A QR code shown at a gate cannot rely on the network — the scanner is on a
bus or standing at a hostel door. So the capability travels inside the code
itself, signed with the platform's shared HS256 key, and the scanner
verifies it locally.

These are deliberately NOT JWTs used for authentication: they carry a
``kind`` that scopes them to exactly one purpose, they live for seconds
rather than minutes, and they must never be accepted in an Authorization
header. ``JWTAuthentication`` will reject them anyway (no ``sub``/``role``
claims), but the ``kind`` check is the explicit guard.
"""

import secrets
import time

import jwt
from django.conf import settings


class SignedTokenError(Exception):
    """The token is malformed, tampered with, expired, or the wrong kind."""


def sign(payload: dict, ttl_seconds: int) -> str:
    """Sign a capability payload. ``kind`` and ``tenant_id`` are required."""
    if "kind" not in payload or "tenant_id" not in payload:
        raise ValueError("Signed tokens require 'kind' and 'tenant_id'.")

    now = int(time.time())
    claims = {
        **payload,
        "iat": now,
        "exp": now + ttl_seconds,
        # A fresh nonce per mint is what makes a screenshot useless: the
        # scanner records nonces it has seen and refuses a repeat.
        "nonce": secrets.token_urlsafe(12),
    }
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")


def verify(token: str, expected_kind: str) -> dict:
    """Verify signature, expiry, and kind. Returns the claims."""
    try:
        claims = jwt.decode(token, settings.JWT_SIGNING_KEY, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise SignedTokenError(str(exc)) from exc

    if claims.get("kind") != expected_kind:
        raise SignedTokenError(f"Token is for '{claims.get('kind')}', not '{expected_kind}'.")

    return claims
