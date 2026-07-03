"""Exam domain model (prototype/stub).

``ExamSchedule`` is a ``suerp_common.tenancy.TenantModel`` subclass, so
``objects`` is transparently tenant-scoped. ``course_id`` is a bare UUID — the
course table lives in another service's database (DB-per-service).
"""

import uuid

from django.db import models
from suerp_common.tenancy import TenantModel


class ExamSchedule(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course_id = models.UUIDField()
    exam_date = models.DateField()
    room_no = models.CharField(max_length=50)
    duration_minutes = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.course_id} {self.exam_date}"
