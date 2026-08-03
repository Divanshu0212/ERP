"""Bus-pass capability tokens over the shared signer."""

from suerp_common.signed_token import sign, verify

KIND = "bus_pass"

#: Short enough that a screenshot is stale before it can be forwarded,
#: long enough that a student holding up a phone in a queue still scans.
PASS_TTL_SECONDS = 30


def mint(tenant_id, pass_id, student_user_code: str) -> str:
    return sign(
        {
            "kind": KIND,
            "tenant_id": str(tenant_id),
            "pass_id": str(pass_id),
            "student_user_code": student_user_code,
        },
        ttl_seconds=PASS_TTL_SECONDS,
    )


def read(token: str) -> dict:
    return verify(token, expected_kind=KIND)
