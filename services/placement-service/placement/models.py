"""Placement domain model (prototype/stub).

``Drive`` is a ``suerp_common.tenancy.TenantModel`` subclass, so ``objects`` is
transparently tenant-scoped and ``all_objects`` bypasses scoping.
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class Drive(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_name = models.CharField(max_length=255)
    job_title = models.CharField(max_length=255)
    ctc = models.DecimalField(max_digits=10, decimal_places=2)
    eligibility = models.CharField(max_length=255)
    drive_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.company_name} - {self.job_title}"
