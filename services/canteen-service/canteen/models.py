"""Canteen domain model (prototype/stub).

``MenuItem`` is a ``suerp_common.tenancy.TenantModel`` subclass, so ``objects``
is transparently tenant-scoped and ``all_objects`` bypasses scoping.
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class MenuItem(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
