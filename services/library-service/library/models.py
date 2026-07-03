"""Library domain model (prototype/stub).

``Book`` is a ``suerp_common.tenancy.TenantModel`` subclass, so ``objects`` is
transparently tenant-scoped and ``all_objects`` bypasses scoping.
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class Book(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    isbn = models.CharField(max_length=20)
    title = models.CharField(max_length=255)
    author = models.CharField(max_length=255)
    category = models.CharField(max_length=100)
    total_copies = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.isbn})"
