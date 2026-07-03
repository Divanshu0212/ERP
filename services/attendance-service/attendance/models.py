"""Attendance domain model (prototype/stub).

``AttendanceRecord`` is a ``suerp_common.tenancy.TenantModel`` subclass, so
``objects`` is transparently tenant-scoped. ``student_id`` / ``course_id`` are
bare UUIDs — those tables live in other services' databases (DB-per-service).
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class AttendanceRecord(TenantModel):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student_id = models.UUIDField()
    course_id = models.UUIDField()
    date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student_id} {self.date} ({self.status})"
