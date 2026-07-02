import uuid

from suerp_common.tenancy import TenantMiddleware, get_current_tenant


class _FakeRequest:
    def __init__(self, tenant_id=None, host="api.suerp.app"):
        self.tenant_id = tenant_id
        self._host = host

    def get_host(self):
        return self._host


def test_middleware_sets_tenant_from_request_attr_and_clears_after():
    tid = str(uuid.uuid4())
    seen = {}

    def get_response(request):
        seen["tenant"] = get_current_tenant()
        return "response"

    mw = TenantMiddleware(get_response)
    result = mw(_FakeRequest(tenant_id=tid))

    assert result == "response"
    assert seen["tenant"] == tid
    # cleared after the response so context doesn't leak to the next request
    assert get_current_tenant() is None


def test_middleware_falls_back_to_subdomain():
    seen = {}

    def get_response(request):
        seen["tenant"] = get_current_tenant()
        return "ok"

    mw = TenantMiddleware(get_response)
    mw(_FakeRequest(tenant_id=None, host="college-x.suerp.app"))

    assert seen["tenant"] == "college-x"
    assert get_current_tenant() is None
