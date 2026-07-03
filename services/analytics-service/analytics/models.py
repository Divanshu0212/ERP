"""Analytics domain model (prototype/stub).

``MetricSnapshot`` is a ``suerp_common.tenancy.TenantModel`` subclass, so
``objects`` is transparently tenant-scoped and ``all_objects`` bypasses scoping.
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class MetricSnapshot(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    metric = models.CharField(max_length=255)
    value = models.FloatField()
    captured_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.metric}={self.value}"
