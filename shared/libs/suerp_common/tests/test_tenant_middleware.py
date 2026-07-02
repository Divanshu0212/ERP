import uuid

import jwt
from suerp_common.tenancy import TenantMiddleware, get_current_tenant

SIGNING_KEY = "test-jwt-key-at-least-32-bytes-long-000"  # matches tests/settings.JWT_SIGNING_KEY


class _FakeRequest:
    """Mimics a real Django/DRF request: headers live in ``.META``, and
    ``tenant_id`` is NOT pre-set — on a real request nothing sets it before
    the middleware's pre-phase runs (JWTAuthentication.authenticate() only
    runs later, inside view dispatch).
    """

    def __init__(self, authorization=None, host="api.suerp.app"):
        self.META = {"HTTP_AUTHORIZATION": authorization or ""}
        self._host = host

    def get_host(self):
        return self._host


def _token(claims, key=SIGNING_KEY):
    return jwt.encode(claims, key, algorithm="HS256")


def _claims(role="student", tenant=None, sub=None):
    return {
        "sub": sub or str(uuid.uuid4()),
        "role": role,
        "tenant": tenant or str(uuid.uuid4()),
    }


def test_middleware_resolves_tenant_from_bearer_token_pre_phase():
    # The real-request scenario: request.tenant_id is NOT pre-set (DRF hasn't
    # run authenticate() yet). The middleware must decode the JWT itself in
    # its pre-phase to get the right tenant.
    claims = _claims()
    req = _FakeRequest(authorization=f"Bearer {_token(claims)}")
    seen = {}

    def get_response(request):
        seen["tenant"] = get_current_tenant()
        return "response"

    mw = TenantMiddleware(get_response)
    result = mw(req)

    assert result == "response"
    assert seen["tenant"] == claims["tenant"]
    # stashed for downstream code/tests that read request.tenant_id directly
    assert req.tenant_id == claims["tenant"]
    # cleared after the response so context doesn't leak to the next request
    assert get_current_tenant() is None


def test_middleware_falls_back_to_subdomain_when_no_token():
    seen = {}

    def get_response(request):
        seen["tenant"] = get_current_tenant()
        return "ok"

    mw = TenantMiddleware(get_response)
    mw(_FakeRequest(authorization=None, host="college-x.suerp.app"))

    assert seen["tenant"] == "college-x"
    assert get_current_tenant() is None


def test_middleware_treats_invalid_token_as_anonymous_without_crashing():
    # A tampered/invalid token must not crash the middleware — it's a
    # best-effort tenant resolution, not a second auth gate. DRF's
    # JWTAuthentication will still reject the request properly in the view.
    req = _FakeRequest(authorization=f"Bearer {_token(_claims(), key='attacker-key')}")
    seen = {}

    def get_response(request):
        seen["tenant"] = get_current_tenant()
        return "ok"

    mw = TenantMiddleware(get_response)
    result = mw(req)

    assert result == "ok"
    assert seen["tenant"] is None
    assert get_current_tenant() is None
