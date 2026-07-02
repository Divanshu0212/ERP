import uuid

import jwt
import pytest
from rest_framework.exceptions import AuthenticationFailed
from suerp_common.auth import JWTAuthentication

SIGNING_KEY = "test-jwt-key-at-least-32-bytes-long-000"  # matches tests/settings.JWT_SIGNING_KEY


class _Req:
    def __init__(self, headers):
        self.headers = headers
        self.META = {"HTTP_AUTHORIZATION": headers.get("Authorization", "")}


def _token(claims, key=SIGNING_KEY):
    return jwt.encode(claims, key, algorithm="HS256")


def _claims(role="student", tenant=None, sub=None):
    return {
        "sub": sub or str(uuid.uuid4()),
        "role": role,
        "tenant": tenant or str(uuid.uuid4()),
    }


def test_valid_token_yields_user_with_role_and_tenant():
    claims = _claims(role="warden")
    req = _Req({"Authorization": f"Bearer {_token(claims)}"})

    user, token_claims = JWTAuthentication().authenticate(req)

    assert user.is_authenticated
    assert user.role == "warden"
    assert user.tenant_id == claims["tenant"]
    assert str(user.id) == claims["sub"]
    # the auth backend stamps the request so TenantMiddleware can read it
    assert req.tenant_id == claims["tenant"]


def test_token_signed_with_wrong_key_is_rejected():
    req = _Req({"Authorization": f"Bearer {_token(_claims(), key='attacker-key')}"})
    with pytest.raises(AuthenticationFailed):
        JWTAuthentication().authenticate(req)


def test_header_only_role_carries_no_authority():
    # No bearer token — only a spoofed role header. Must be treated as anonymous.
    req = _Req({"X-User-Role": "admin"})
    result = JWTAuthentication().authenticate(req)
    assert result is None
