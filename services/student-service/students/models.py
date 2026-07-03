"""Student domain model (prototype/stub).

``StudentProfile`` is a ``suerp_common.tenancy.TenantModel`` subclass, so
``objects`` is transparently tenant-scoped and ``all_objects`` bypasses it.
``user_id`` is a bare UUID — auth-service owns the User table in its own
database (DB-per-service), so this is only ever an opaque reference.
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class StudentProfile(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField()
    roll_no = models.CharField(max_length=50)
    department = models.CharField(max_length=100)
    batch = models.CharField(max_length=20)
    semester = models.PositiveSmallIntegerField(default=1)
    cgpa = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.roll_no} ({self.department})"
