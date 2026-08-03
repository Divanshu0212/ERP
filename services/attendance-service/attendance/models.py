"""Attendance domain models.

``AttendanceRecord`` is the original day/course roll (kept: the
``/api/v1/attendance/`` list endpoint still serves it). ``Session`` and
``AttendanceMark`` are the geofenced flow: a Session is one class meeting,
pinned to a location, and a student may mark attendance only from inside
that circle, with the code currently on the faculty's screen, once. Those
three constraints together are what make proxy attendance meaningfully
harder than "a friend taps a button".

All three are ``suerp_common.tenancy.TenantModel`` subclasses, so ``objects``
is transparently tenant-scoped. ``student_user_code``/``faculty_id``
reference auth-service users by opaque code, never by FK — those rows live
in another service's database.
"""

import math
import uuid

from django.db import models
from suerp_common.tenancy import TenantModel

EARTH_RADIUS_M = 6_371_000


def haversine_metres(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance. Exact enough at classroom scale, and it needs
    no PostGIS — adding a spatial extension for one circle test would be a
    large dependency for a small question."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


class AttendanceRecord(TenantModel):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student_user_code = models.CharField(max_length=30)
    course_id = models.UUIDField()
    date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.student_user_code} {self.date} ({self.status})"


class Session(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course_code = models.CharField(max_length=50)
    faculty_id = models.CharField(max_length=30)
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    radius_m = models.PositiveSmallIntegerField(default=50)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["course_code", "opened_at"], name="session_course_time"),
        ]

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    def contains(self, lat: float, lng: float) -> float | None:
        """Distance in metres if inside the fence, else None."""
        distance = haversine_metres(float(self.lat), float(self.lng), lat, lng)
        return distance if distance <= self.radius_m else None

    def __str__(self):
        return f"{self.course_code} @ {self.opened_at}"


class AttendanceMark(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="marks")
    student_user_code = models.CharField(max_length=30)
    distance_m = models.FloatField()
    #: Reported by the device. Recorded even on refusal, because a pattern of
    #: mock-location attempts is itself worth seeing.
    mock_location = models.BooleanField(default=False)
    marked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "student_user_code"],
                name="one_mark_per_student_per_session",
            ),
        ]

    def __str__(self):
        return f"{self.student_user_code} @ {self.session_id}"
