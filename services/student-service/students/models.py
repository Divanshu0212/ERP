"""Student domain model (prototype/stub).

``StudentProfile`` is a ``suerp_common.tenancy.TenantModel`` subclass, so
``objects`` is transparently tenant-scoped and ``all_objects`` bypasses it.
``user_code`` is a bare string — auth-service owns the User table in its own
database (DB-per-service), so this is only ever an opaque reference. It is
also the student's roll number: there is one roll-number concept
platform-wide (auth-service's ``User.user_code``), not a separate per-student
``roll_no`` field.
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class StudentProfile(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_code = models.CharField(max_length=30)
    department = models.CharField(max_length=100)
    batch = models.CharField(max_length=20)
    semester = models.PositiveSmallIntegerField(default=1)
    cgpa = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user_code} ({self.department})"
