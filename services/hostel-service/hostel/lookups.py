"""Synchronous cross-service lookup: resolve a user's email to their
auth-service User.id.

hostel-service has no user table of its own (every service verifies JWTs
issued by auth-service — see suerp_common.auth — and never owns identity).
The warden's allocation and block-creation forms accept a student/warden
EMAIL rather than a raw UUID, so this makes exactly one synchronous HTTP
call through the gateway to auth-service's GET /accounts/users/by-email/
endpoint, forwarding the caller's own bearer token unchanged (that endpoint
is warden/admin-only, so the caller must already hold a token with
sufficient privilege — there is no separate service-to-service credential).

This is the first synchronous inter-service call among the Django
services; every other cross-service reference in this platform flows
through the async transactional-outbox/inbox pattern in suerp_common. It
stays narrow and local to hostel-service rather than becoming a shared
library, since no other service needs it today.
"""

import requests
from django.conf import settings


class LookupFailed(Exception):
    """Raised when a by-email lookup can't be resolved.

    ``reason`` is "not_found" (the email doesn't match any user in the
    caller's tenant — a 400 to the caller) or "unavailable" (timeout,
    connection error, or a non-2xx/non-404 from auth-service — a 502,
    since we can't tell whether the email itself is valid).
    """

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(detail or reason)


def resolve_user_by_email(email: str, auth_header: str | None) -> dict:
    """Resolve ``email`` to ``{id, email, role}`` via auth-service.

    ``auth_header`` is the inbound request's full ``Authorization: Bearer
    <token>`` value, forwarded unchanged so auth-service's own
    role_required("warden", "admin") check applies to the ORIGINAL caller.
    """
    url = f"{settings.GATEWAY_URL}/api/v1/auth/users/by-email/"
    headers = {"Authorization": auth_header} if auth_header else {}

    try:
        response = requests.get(url, params={"email": email}, headers=headers, timeout=5)
    except requests.RequestException as exc:
        raise LookupFailed("unavailable", str(exc)) from exc

    if response.status_code == 404:
        raise LookupFailed("not_found", f"No user found with email {email}.")
    if not response.ok:
        raise LookupFailed("unavailable", f"auth-service returned {response.status_code}.")

    try:
        envelope = response.json()
    except ValueError as exc:
        raise LookupFailed("unavailable", "Invalid response from auth-service.") from exc

    if not envelope.get("success"):
        raise LookupFailed(
            "not_found", envelope.get("message") or f"No user found with email {email}."
        )

    return envelope["data"]
