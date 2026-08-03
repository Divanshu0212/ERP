"""Time-bucketed codes displayed on the faculty's dashboard.

A code derived from (session, current 15-second bucket) means a student who
photographs the projector and sends it to a friend across campus has sent
something that is already dead — and the geofence stops the friend anyway.
Two independent checks, each cheap.
"""

import hashlib
import hmac
import time

from django.conf import settings

#: Short enough that a forwarded screenshot expires in transit; long enough
#: that a student typing it in is not racing a clock.
CODE_PERIOD_SECONDS = 15
CODE_DIGITS = 6


def _bucket(at: float | None = None) -> int:
    return int((at if at is not None else time.time()) // CODE_PERIOD_SECONDS)


def _code_for_bucket(session_id, bucket: int) -> str:
    message = f"{session_id}:{bucket}".encode()
    digest = hmac.new(settings.JWT_SIGNING_KEY.encode(), message, hashlib.sha256).digest()
    number = int.from_bytes(digest[:4], "big") % (10**CODE_DIGITS)
    return str(number).zfill(CODE_DIGITS)


def current_code(session_id) -> str:
    return _code_for_bucket(session_id, _bucket())


def is_code_valid(session_id, code: str) -> bool:
    """Accepts the current bucket and the previous one.

    The one-bucket grace exists because a student can read a code at 14.9
    seconds and submit at 15.1 — refusing that would make the feature feel
    broken for a reason the student cannot see.
    """
    now = _bucket()
    return any(
        hmac.compare_digest(_code_for_bucket(session_id, bucket), code)
        for bucket in (now, now - 1)
    )
