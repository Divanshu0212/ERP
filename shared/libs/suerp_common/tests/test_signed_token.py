"""Short-lived signed capability tokens (QR passes, pickup tokens).

These are NOT authentication tokens. They assert one narrow capability for
a few seconds and are verified offline by a scanner device that may have no
network at all.
"""

import time
import uuid

import pytest
from suerp_common.signed_token import SignedTokenError, sign, verify

TENANT = str(uuid.uuid4())


def test_a_signed_token_round_trips():
    token = sign({"kind": "bus_pass", "tenant_id": TENANT, "pass_id": "p1"}, ttl_seconds=30)

    claims = verify(token, expected_kind="bus_pass")

    assert claims["pass_id"] == "p1"
    assert claims["tenant_id"] == TENANT


def test_every_token_gets_a_unique_nonce():
    payload = {"kind": "bus_pass", "tenant_id": TENANT, "pass_id": "p1"}

    first = verify(sign(payload, ttl_seconds=30), expected_kind="bus_pass")
    second = verify(sign(payload, ttl_seconds=30), expected_kind="bus_pass")

    assert first["nonce"] != second["nonce"]


def test_a_tampered_token_is_rejected():
    token = sign({"kind": "bus_pass", "tenant_id": TENANT, "pass_id": "p1"}, ttl_seconds=30)
    tampered = token[:-4] + "AAAA"

    with pytest.raises(SignedTokenError):
        verify(tampered, expected_kind="bus_pass")


def test_a_token_of_the_wrong_kind_is_rejected():
    """A pickup token must never open a bus gate."""
    token = sign({"kind": "pickup", "tenant_id": TENANT, "order_id": "o1"}, ttl_seconds=30)

    with pytest.raises(SignedTokenError):
        verify(token, expected_kind="bus_pass")


def test_an_expired_token_is_rejected():
    token = sign({"kind": "bus_pass", "tenant_id": TENANT, "pass_id": "p1"}, ttl_seconds=1)
    time.sleep(2)

    with pytest.raises(SignedTokenError):
        verify(token, expected_kind="bus_pass")
