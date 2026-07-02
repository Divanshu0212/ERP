"""Tenant isolation primitives.

Multi-tenancy model: shared database, shared schema, row-level ``tenant_id``.
The active tenant is stored in a context variable (async/thread safe) and every
tenant-owned queryset is auto-filtered by ``TenantManager``. ``TenantMiddleware``
resolves the tenant itself in its pre-phase — best-effort decoding the request's
bearer token (falling back to the subdomain when there is none) — since it runs
before DRF's ``JWTAuthentication`` does. It always clears the context after the
response.
"""

import contextvars

from django.db import models
from rest_framework.exceptions import AuthenticationFailed

from .auth import decode_bearer_token

_current_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_tenant", default=None
)


def set_current_tenant(tenant_id: str | None) -> None:
    _current_tenant.set(tenant_id)


def get_current_tenant() -> str | None:
    return _current_tenant.get()


class TenantManager(models.Manager):
    """Manager that transparently scopes every queryset to the active tenant.

    When no tenant is set (e.g. management commands, system tasks) the queryset
    is returned unfiltered — callers in request context always have a tenant.
    """

    def get_queryset(self):
        qs = super().get_queryset()
        tenant = get_current_tenant()
        if tenant is None:
            return qs
        return qs.filter(tenant_id=tenant)


class TenantModel(models.Model):
    """Abstract base for every tenant-owned model.

    ``objects`` is tenant-scoped; ``all_objects`` bypasses scoping for
    cross-tenant system operations (event consumers that resolve tenant from
    the event payload, migrations, admin tooling).
    """

    tenant_id = models.UUIDField(db_index=True)

    objects = TenantManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True


class TenantMiddleware:
    """Resolve the active tenant for the duration of a request.

    Middleware pre-phase runs *before* DRF view dispatch, i.e. before
    ``JWTAuthentication.authenticate()`` ever runs — so ``request.tenant_id``
    cannot be relied on as already-populated at this point. Instead this
    middleware decodes the bearer token itself (best-effort) to resolve the
    tenant early, and also stashes the result on ``request.tenant_id`` so
    downstream code (and ``JWTAuthentication``, tests, etc.) can read it. As a
    fallback (e.g. unauthenticated tenant-scoped landing pages, or no token at
    all) the leftmost subdomain label is used. The tenant is always cleared in
    a ``finally`` so context never leaks across requests on a reused worker.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            tenant = None
            token_present_but_invalid = False
            try:
                # Note: this verifies the JWT signature here (best-effort, for
                # tenant context), and JWTAuthentication verifies it again
                # later (authoritatively, for identity/authorization). That's
                # up to two HS256 verifications per request — cheap, and
                # simpler than trying to cache/share the decoded claims across
                # the middleware/DRF boundary, which would couple them tightly
                # for little benefit.
                claims = decode_bearer_token(request)
            except AuthenticationFailed:
                # An invalid/expired/tampered token must not crash the
                # middleware — this is not a second auth gate, just a
                # best-effort tenant resolution for context. DRF's
                # JWTAuthentication will still run in the view and return the
                # proper 401 envelope for protected endpoints. Treat as
                # anonymous here (tenant=None) and let request handling
                # continue; the view is responsible for rejecting the request.
                claims = None
                token_present_but_invalid = True

            if claims is not None:
                tenant = claims["tenant"]
                # Stash so downstream code/tests can read request.tenant_id
                # without needing to re-decode the token.
                request.tenant_id = tenant
            elif not token_present_but_invalid:
                # No bearer token at all -> fall back to subdomain. (A present
                # but invalid token stays anonymous; we don't guess a tenant
                # from the host in that case.)
                host = request.get_host().split(":")[0]
                labels = host.split(".")
                if len(labels) > 2:  # <slug>.suerp.app
                    tenant = labels[0]
            set_current_tenant(tenant)
            return self.get_response(request)
        finally:
            set_current_tenant(None)
