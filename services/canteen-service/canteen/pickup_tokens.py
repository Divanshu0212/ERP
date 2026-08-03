"""Pickup capability tokens over the shared signer."""

from suerp_common.signed_token import sign, verify

KIND = "pickup"

#: Longer than a bus pass — a student walks up to a counter and waits in a
#: queue, which takes more than thirty seconds.
PICKUP_TTL_SECONDS = 300


def mint(tenant_id, order_id) -> str:
    return sign(
        {"kind": KIND, "tenant_id": str(tenant_id), "order_id": str(order_id)},
        ttl_seconds=PICKUP_TTL_SECONDS,
    )


def read(token: str) -> dict:
    return verify(token, expected_kind=KIND)
