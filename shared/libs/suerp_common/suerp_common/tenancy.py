"""Tenant isolation primitives.

Multi-tenancy model: shared database, shared schema, row-level ``tenant_id``.
The active tenant is stored in a context variable (async/thread safe) and every
tenant-owned queryset is auto-filtered by ``TenantManager``. ``TenantMiddleware``
sets the context from the authenticated JWT claim (or subdomain fallback) and
always clears it after the response.
"""

import contextvars

from django.db import models

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

    Primary source is ``request.tenant_id`` populated by ``JWTAuthentication``
    during DRF auth. As a fallback (e.g. unauthenticated tenant-scoped landing
    pages) the leftmost subdomain label is used. The tenant is always cleared in
    a ``finally`` so context never leaks across requests on a reused worker.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            tenant = getattr(request, "tenant_id", None)
            if tenant is None:
                host = request.get_host().split(":")[0]
                labels = host.split(".")
                if len(labels) > 2:  # <slug>.suerp.app
                    tenant = labels[0]
            set_current_tenant(tenant)
            return self.get_response(request)
        finally:
            set_current_tenant(None)
