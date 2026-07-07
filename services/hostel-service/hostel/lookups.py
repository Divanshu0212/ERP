"""Synchronous cross-service lookup: resolve a user_code to its identity via
auth-service.

hostel-service has no user table of its own (every service verifies JWTs
issued by auth-service — see suerp_common.auth — and never owns identity).
The warden's allocation and block-creation forms accept a student/warden
user_code directly, so this makes exactly one synchronous HTTP call through
the gateway to auth-service's GET /accounts/users/by-code/ endpoint,
forwarding the caller's own bearer token unchanged (that endpoint is
warden/admin-only, so the caller must already hold a token with sufficient
privilege — there is no separate service-to-service credential).

This is the first synchronous inter-service call among the Django
services; every other cross-service reference in this platform flows
through the async transactional-outbox/inbox pattern in suerp_common.
"""

import requests
from django.conf import settings


class LookupFailed(Exception):
    """Raised when a by-user_code lookup can't be resolved.

    ``reason`` is "not_found" (the user_code doesn't match any user in the
    caller's tenant — a 400 to the caller) or "unavailable" (timeout,
    connection error, or a non-2xx/non-404 from auth-service — a 502).
    """

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(detail or reason)


def resolve_user_by_code(user_code: str, auth_header: str | None) -> dict:
    """Resolve ``user_code`` to ``{user_code, email, role}`` via auth-service.

    ``auth_header`` is the inbound request's full ``Authorization: Bearer
    <token>`` value, forwarded unchanged so auth-service's own
    role_required("warden", "admin") check applies to the ORIGINAL caller.
    """
    url = f"{settings.GATEWAY_URL}/api/v1/auth/users/by-code/"
    headers = {"Authorization": auth_header} if auth_header else {}

    try:
        response = requests.get(url, params={"user_code": user_code}, headers=headers, timeout=5)
    except requests.RequestException as exc:
        raise LookupFailed("unavailable", str(exc)) from exc

    if response.status_code == 404:
        raise LookupFailed("not_found", f"No user found with user_code {user_code}.")
    if not response.ok:
        raise LookupFailed("unavailable", f"auth-service returned {response.status_code}.")

    try:
        envelope = response.json()
    except ValueError as exc:
        raise LookupFailed("unavailable", "Invalid response from auth-service.") from exc

    if not envelope.get("success"):
        raise LookupFailed(
            "not_found", envelope.get("message") or f"No user found with user_code {user_code}."
        )

    return envelope["data"]


def resolve_institution_name(auth_header: str | None) -> str:
    """Resolve the caller's own institution display name via auth-service.

    Unchanged by this migration — see hostel/lookups.py history for rationale.
    """
    url = f"{settings.GATEWAY_URL}/api/v1/auth/institution"
    headers = {"Authorization": auth_header} if auth_header else {}

    try:
        response = requests.get(url, headers=headers, timeout=5)
    except requests.RequestException:
        return ""

    if not response.ok:
        return ""

    try:
        envelope = response.json()
    except ValueError:
        return ""

    if not envelope.get("success"):
        return ""

    return envelope.get("data", {}).get("name", "")
