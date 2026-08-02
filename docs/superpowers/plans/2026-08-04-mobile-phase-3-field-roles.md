# Mobile Phase 3 — Warden, Driver & Canteen-Owner Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the three staff surfaces that are genuinely mobile jobs — warden walking blocks, driver on the bus, canteen owner in the kitchen — and close the three backend gaps they depend on.

**Architecture:** Backend first (Tasks 1–3), because every screen in this phase calls at least one endpoint that does not exist yet: `VisitorLog` in hostel-service, driver trip start/end in transport-service, and `PATCH /status` in grievance-service. Then the three role shells, each reusing the Phase 2 pattern (api module → hook → screen) and the Phase 1 offline queue. These roles are where the write queue earns its keep: four of their five mutations queue.

**Tech Stack:** Django 5 + DRF (backend); Expo Router, TanStack Query, `expo-sqlite` queue (app).

## Global Constraints

- Prerequisites: **Phases 1 and 2 are merged.** This plan consumes `request`, `ApiError`, `enqueue`, `useConnectivity`, `OfflineBanner`, `Money`, `cacheAge`, and the `shared/api-types/` modules.
- Spec: `docs/superpowers/specs/2026-08-02-mobile-app-design.md` §5.2–§5.5. Branch: `feat/mobile-app`.
- Backend services here are **tenant-scoped via `TenantModel`** (unlike auth-service). New models subclass `suerp_common.tenancy.TenantModel` and are queried through the tenant-filtering default manager — do not add an explicit `tenant` FK to `Institution`, which only exists in auth-service's database.
- Every new endpoint gets a cross-tenant isolation test, matching the existing per-service convention.
- Role gating uses `suerp_common.permissions.role_required(...)`, never a hand-rolled check.
- Responses use `ok()`/`fail()` from `suerp_common.envelope`.
- **Queueable mutations in this phase:** order status advance, visitor log entry, grievance status change, and GPS breadcrumb batches. Everything else is online-only.
- Money fields arrive as strings. Never do arithmetic without `Number()`.
- Commit as `Divanshu0212 <divanshubhargava026@gmail.com>`, no co-author trailer. Commit after every task.

---

## File Structure

**Backend**

| File | Responsibility |
| --- | --- |
| `services/hostel-service/hostel/models.py` (modify) | add `VisitorLog` |
| `services/hostel-service/hostel/views.py` (modify) | `VisitorLogListCreateView`, `VisitorCheckoutView` |
| `services/hostel-service/hostel/tests/test_visitor_log.py` (create) | CRUD + tenant isolation |
| `services/transport-service/transport/models.py` (modify) | add `Trip`, `Breadcrumb` |
| `services/transport-service/transport/views.py` (modify) | trip start/end, breadcrumb ingest, live position |
| `services/transport-service/transport/tests/test_trips.py` (create) | trip lifecycle + ownership |
| `services/grievance-service/grievance/views.py` (modify) | `GrievanceStatusView` |
| `services/grievance-service/grievance/tests/test_status.py` (create) | legal transitions + role gating |

**App**

| File | Responsibility |
| --- | --- |
| `src/lib/api/warden.ts` | roster, allocations, leave requests, visitor log |
| `src/lib/api/driver.ts` | schedules, trips, breadcrumbs, manifest |
| `src/lib/api/owner.ts` | order board, status advance, menu management |
| `src/features/warden/`, `driver/`, `owner/` | hooks + screens |
| `app/(warden)/`, `app/(driver)/`, `app/(canteen-owner)/` | tab shells and routes |

---

## Task 1: `VisitorLog` in hostel-service

**Files:**
- Modify: `services/hostel-service/hostel/models.py`
- Modify: `services/hostel-service/hostel/views.py`
- Modify: `services/hostel-service/hostel/urls.py`
- Modify: `services/hostel-service/hostel/serializers.py`
- Create: `services/hostel-service/hostel/tests/test_visitor_log.py`

**Interfaces:**
- Consumes: `TenantModel` from `suerp_common.tenancy`, `role_required` from `suerp_common.permissions`.
- Produces:
  - `VisitorLog` model: `id: UUID`, `visitor_name`, `visiting_user_code`, `purpose`, `phone`, `checked_in_at`, `checked_out_at: datetime|None`, `logged_by`
  - `GET/POST /api/v1/hostel/visitors` (warden/admin)
  - `POST /api/v1/hostel/visitors/<uuid:pk>/checkout` (warden/admin)

- [ ] **Step 1: Read the existing patterns**

Run: `grep -n "class Complaint" -A 20 services/hostel-service/hostel/models.py` and `grep -n "class BlockListCreateView" -A 25 services/hostel-service/hostel/views.py`
Record: how `TenantModel` subclasses declare fields, and how a list/create view gates roles and sets `tenant_id` on save. Follow that shape exactly below.

- [ ] **Step 2: Write the failing tests**

Create `services/hostel-service/hostel/tests/test_visitor_log.py`:

```python
"""Warden visitor log: gate entries recorded on a phone, often offline."""

import uuid

import pytest
from hostel.models import VisitorLog
from rest_framework.test import APIClient
from suerp_common.tenancy import set_current_tenant

pytestmark = pytest.mark.django_db

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _client(tenant_id, role="warden", sub="WRD-001"):
    """An APIClient carrying a verified-shape JWT for this tenant and role.

    Mirrors the auth fixture used by the existing hostel tests — read
    hostel/tests/conftest.py and reuse its helper if one already exists
    rather than duplicating token construction here.
    """
    from tests.helpers import auth_client  # noqa: PLC0415

    return auth_client(tenant_id=tenant_id, role=role, sub=sub)


def test_warden_can_log_a_visitor():
    client = _client(TENANT_A)

    response = client.post(
        "/api/v1/hostel/visitors",
        {"visitor_name": "Asha Rao", "visiting_user_code": "STU-001", "purpose": "Parent visit"},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["data"]["visitor_name"] == "Asha Rao"
    assert response.json()["data"]["checked_out_at"] is None


def test_checkout_stamps_the_exit_time():
    client = _client(TENANT_A)
    created = client.post(
        "/api/v1/hostel/visitors",
        {"visitor_name": "Asha Rao", "visiting_user_code": "STU-001", "purpose": "Parent visit"},
        format="json",
    ).json()["data"]

    response = client.post(f"/api/v1/hostel/visitors/{created['id']}/checkout", format="json")

    assert response.status_code == 200
    assert response.json()["data"]["checked_out_at"] is not None


def test_checking_out_twice_is_rejected():
    client = _client(TENANT_A)
    created = client.post(
        "/api/v1/hostel/visitors",
        {"visitor_name": "Asha Rao", "visiting_user_code": "STU-001", "purpose": "Visit"},
        format="json",
    ).json()["data"]
    client.post(f"/api/v1/hostel/visitors/{created['id']}/checkout", format="json")

    response = client.post(f"/api/v1/hostel/visitors/{created['id']}/checkout", format="json")

    assert response.status_code == 400


def test_students_cannot_log_visitors():
    client = _client(TENANT_A, role="student", sub="STU-001")

    response = client.post(
        "/api/v1/hostel/visitors",
        {"visitor_name": "Asha Rao", "visiting_user_code": "STU-001", "purpose": "Visit"},
        format="json",
    )

    assert response.status_code == 403


def test_visitor_logs_do_not_leak_across_tenants():
    client_a = _client(TENANT_A)
    client_a.post(
        "/api/v1/hostel/visitors",
        {"visitor_name": "Asha Rao", "visiting_user_code": "STU-001", "purpose": "Visit"},
        format="json",
    )

    client_b = _client(TENANT_B, sub="WRD-002")
    response = client_b.get("/api/v1/hostel/visitors")

    assert response.status_code == 200
    assert response.json()["data"]["results"] == []
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd services/hostel-service && python -m pytest hostel/tests/test_visitor_log.py -v`
Expected: FAIL — `ImportError: cannot import name 'VisitorLog'`

- [ ] **Step 4: Add the model**

Append to `services/hostel-service/hostel/models.py`:

```python
class VisitorLog(TenantModel):
    """A visitor signed in at the hostel gate.

    Recorded on a warden's phone at the gate, which is exactly where the
    signal is worst — so the app queues these and replays them (see the
    mobile offline queue). ``checked_out_at`` stays null until the visitor
    leaves, which is what makes "who is still inside" answerable.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visitor_name = models.CharField(max_length=255)
    visiting_user_code = models.CharField(max_length=30)
    purpose = models.CharField(max_length=255, blank=True, default="")
    phone = models.CharField(max_length=20, blank=True, default="")
    logged_by = models.CharField(max_length=30)
    checked_in_at = models.DateTimeField(auto_now_add=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["visiting_user_code"], name="visitor_student_idx"),
        ]

    def __str__(self):
        return f"{self.visitor_name} → {self.visiting_user_code}"
```

- [ ] **Step 5: Add the serializer**

Append to `services/hostel-service/hostel/serializers.py`:

```python
class VisitorLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisitorLog
        fields = [
            "id",
            "visitor_name",
            "visiting_user_code",
            "purpose",
            "phone",
            "logged_by",
            "checked_in_at",
            "checked_out_at",
        ]
        read_only_fields = ["id", "logged_by", "checked_in_at", "checked_out_at"]
```

Add `VisitorLog` to the model imports at the top of the file.

- [ ] **Step 6: Add the views**

Append to `services/hostel-service/hostel/views.py` (add `VisitorLog` and `VisitorLogSerializer` to the imports):

```python
class VisitorLogListCreateView(ListCreateAPIView):
    """GET/POST /api/v1/hostel/visitors — the gate register.

    GET defaults to visitors still inside (``checked_out_at`` is null), which
    is the question a warden at the gate actually has. ``?all=true`` returns
    the full history.
    """

    permission_classes = [role_required("warden", "admin")]
    serializer_class = VisitorLogSerializer

    def get_queryset(self):
        qs = VisitorLog.objects.all().order_by("-checked_in_at")
        if self.request.query_params.get("all", "").lower() != "true":
            qs = qs.filter(checked_out_at__isnull=True)
        return qs

    def perform_create(self, serializer):
        serializer.save(logged_by=self.request.user.id)


class VisitorCheckoutView(APIView):
    """POST /api/v1/hostel/visitors/<id>/checkout — stamp the exit time."""

    permission_classes = [role_required("warden", "admin")]

    def post(self, request, pk):
        try:
            visitor = VisitorLog.objects.get(pk=pk)
        except VisitorLog.DoesNotExist:
            return fail("Visitor entry not found.", status=404)

        if visitor.checked_out_at is not None:
            return fail("Visitor is already checked out.", status=400)

        visitor.checked_out_at = timezone.now()
        visitor.save(update_fields=["checked_out_at"])
        return ok(VisitorLogSerializer(visitor).data, message="Visitor checked out.")
```

Confirm `ListCreateAPIView`, `timezone`, `APIView`, `ok`, `fail`, and `role_required` are all imported at the top of the file; add any that are missing.

- [ ] **Step 7: Add the routes**

In `services/hostel-service/hostel/urls.py`, import both views and add:

```python
    path("visitors", VisitorLogListCreateView.as_view(), name="visitor-list-create"),
    path("visitors/<uuid:pk>/checkout", VisitorCheckoutView.as_view(), name="visitor-checkout"),
```

- [ ] **Step 8: Migrate and run the tests**

Run: `cd services/hostel-service && python manage.py makemigrations hostel && python -m pytest hostel/tests/ -v`
Expected: the 5 new tests PASS and every pre-existing hostel test still PASSES

- [ ] **Step 9: Commit**

```bash
git add services/hostel-service/
git commit -m "feat(hostel): add warden visitor log with checkout"
```

---

## Task 2: Driver trips and GPS breadcrumbs

**Files:**
- Modify: `services/transport-service/transport/models.py`
- Modify: `services/transport-service/transport/views.py`
- Modify: `services/transport-service/transport/urls.py`
- Modify: `services/transport-service/transport/serializers.py`
- Create: `services/transport-service/transport/tests/test_trips.py`

**Interfaces:**
- Consumes: `BusSchedule`, `Booking`, `Stop` (existing); `role_required`.
- Produces:
  - `Trip` model: `id: UUID`, `schedule: FK[BusSchedule]`, `driver_id`, `started_at`, `ended_at: datetime|None`
  - `Breadcrumb` model: `id: UUID`, `trip: FK[Trip]`, `lat: Decimal`, `lng: Decimal`, `recorded_at`
  - `POST /api/v1/transport/schedules/<uuid:schedule_id>/trips` — start (driver owns the schedule)
  - `POST /api/v1/transport/trips/<uuid:pk>/end`
  - `POST /api/v1/transport/trips/<uuid:pk>/breadcrumbs` — batch ingest, writes last position to Redis
  - `GET /api/v1/transport/routes/<uuid:route_id>/live` — last known position for students

- [ ] **Step 1: Read the Redis caching pattern already in this service**

Run: `grep -rn "cache\." services/transport-service/transport/ | head -20`
Record the exact tenant-namespaced key format used for the seat cache. The live-position key must follow the same convention so one tenant can never read another's bus.

- [ ] **Step 2: Write the failing tests**

Create `services/transport-service/transport/tests/test_trips.py`:

```python
"""Driver trip lifecycle and GPS breadcrumb ingest."""

import uuid

import pytest
from transport.models import Breadcrumb, BusSchedule, Route, Trip

pytestmark = pytest.mark.django_db

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _client(tenant_id, role="driver", sub="DRV-001"):
    """Reuse this service's existing auth test helper — read
    transport/tests/conftest.py and call its fixture rather than
    reconstructing a token here."""
    from tests.helpers import auth_client  # noqa: PLC0415

    return auth_client(tenant_id=tenant_id, role=role, sub=sub)


def _schedule(tenant_id, driver_id="DRV-001"):
    route = Route.objects.create(
        tenant_id=tenant_id, name="North Loop", start_point="Gate", end_point="Campus"
    )
    return BusSchedule.objects.create(
        tenant_id=tenant_id,
        route=route,
        bus_no="KA-01-1234",
        driver_id=driver_id,
        departure_time="2026-08-04T08:00:00Z",
        capacity=40,
    )


def test_driver_starts_a_trip_on_their_own_schedule():
    schedule = _schedule(TENANT_A)
    client = _client(TENANT_A)

    response = client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json")

    assert response.status_code == 201
    assert response.json()["data"]["ended_at"] is None
    assert Trip.objects.count() == 1


def test_driver_cannot_start_a_trip_on_someone_elses_schedule():
    schedule = _schedule(TENANT_A, driver_id="DRV-999")
    client = _client(TENANT_A)

    response = client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json")

    assert response.status_code == 403


def test_starting_a_second_trip_while_one_is_active_is_rejected():
    schedule = _schedule(TENANT_A)
    client = _client(TENANT_A)
    client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json")

    response = client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json")

    assert response.status_code == 400


def test_ending_a_trip_stamps_the_end_time():
    schedule = _schedule(TENANT_A)
    client = _client(TENANT_A)
    trip = client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json").json()[
        "data"
    ]

    response = client.post(f"/api/v1/transport/trips/{trip['id']}/end", format="json")

    assert response.status_code == 200
    assert response.json()["data"]["ended_at"] is not None


def test_breadcrumb_batch_is_stored():
    schedule = _schedule(TENANT_A)
    client = _client(TENANT_A)
    trip = client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json").json()[
        "data"
    ]

    response = client.post(
        f"/api/v1/transport/trips/{trip['id']}/breadcrumbs",
        {
            "points": [
                {"lat": "12.971599", "lng": "77.594566", "recorded_at": "2026-08-04T08:01:00Z"},
                {"lat": "12.972000", "lng": "77.595000", "recorded_at": "2026-08-04T08:01:15Z"},
            ]
        },
        format="json",
    )

    assert response.status_code == 201
    assert Breadcrumb.objects.filter(trip_id=trip["id"]).count() == 2


def test_replaying_the_same_breadcrumb_batch_does_not_duplicate():
    schedule = _schedule(TENANT_A)
    client = _client(TENANT_A)
    trip = client.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json").json()[
        "data"
    ]
    body = {
        "points": [
            {"lat": "12.971599", "lng": "77.594566", "recorded_at": "2026-08-04T08:01:00Z"}
        ]
    }

    client.post(f"/api/v1/transport/trips/{trip['id']}/breadcrumbs", body, format="json")
    client.post(f"/api/v1/transport/trips/{trip['id']}/breadcrumbs", body, format="json")

    assert Breadcrumb.objects.filter(trip_id=trip["id"]).count() == 1


def test_students_can_read_the_live_position():
    schedule = _schedule(TENANT_A)
    driver = _client(TENANT_A)
    trip = driver.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json").json()[
        "data"
    ]
    driver.post(
        f"/api/v1/transport/trips/{trip['id']}/breadcrumbs",
        {"points": [{"lat": "12.971599", "lng": "77.594566", "recorded_at": "2026-08-04T08:01:00Z"}]},
        format="json",
    )

    student = _client(TENANT_A, role="student", sub="STU-001")
    response = student.get(f"/api/v1/transport/routes/{schedule.route_id}/live")

    assert response.status_code == 200
    assert response.json()["data"]["lat"] == "12.971599"


def test_live_position_does_not_leak_across_tenants():
    schedule = _schedule(TENANT_A)
    driver = _client(TENANT_A)
    trip = driver.post(f"/api/v1/transport/schedules/{schedule.id}/trips", format="json").json()[
        "data"
    ]
    driver.post(
        f"/api/v1/transport/trips/{trip['id']}/breadcrumbs",
        {"points": [{"lat": "12.971599", "lng": "77.594566", "recorded_at": "2026-08-04T08:01:00Z"}]},
        format="json",
    )

    other = _client(TENANT_B, role="student", sub="STU-002")
    response = other.get(f"/api/v1/transport/routes/{schedule.route_id}/live")

    assert response.status_code == 404
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd services/transport-service && python -m pytest transport/tests/test_trips.py -v`
Expected: FAIL — `ImportError: cannot import name 'Trip'`

- [ ] **Step 4: Add the models**

Append to `services/transport-service/transport/models.py`:

```python
class Trip(TenantModel):
    """One driver's active run of a schedule.

    A schedule is the timetable entry; a Trip is today's actual execution of
    it. Separating them means the live position and breadcrumb trail belong
    to a specific run and disappear cleanly when it ends.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    schedule = models.ForeignKey(BusSchedule, on_delete=models.CASCADE, related_name="trips")
    driver_id = models.CharField(max_length=30)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["schedule", "ended_at"], name="trip_schedule_active"),
        ]

    def __str__(self):
        return f"Trip {self.id} ({'active' if self.ended_at is None else 'ended'})"


class Breadcrumb(TenantModel):
    """One GPS sample from a running trip.

    ``recorded_at`` is stamped on the device, not the server, because these
    arrive in batches after a signal gap — the server's clock would collapse
    a five-minute tunnel into one instant. The uniqueness constraint makes a
    replayed batch (the offline queue retrying) a no-op rather than a
    duplicated trail.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="breadcrumbs")
    lat = models.DecimalField(max_digits=9, decimal_places=6)
    lng = models.DecimalField(max_digits=9, decimal_places=6)
    recorded_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["trip", "recorded_at"], name="unique_breadcrumb_per_instant"
            ),
        ]
        indexes = [
            models.Index(fields=["trip", "recorded_at"], name="breadcrumb_trip_time"),
        ]

    def __str__(self):
        return f"{self.lat},{self.lng} @ {self.recorded_at}"
```

- [ ] **Step 5: Add the serializers**

Append to `services/transport-service/transport/serializers.py`:

```python
class TripSerializer(serializers.ModelSerializer):
    class Meta:
        model = Trip
        fields = ["id", "schedule", "driver_id", "started_at", "ended_at"]
        read_only_fields = fields


class BreadcrumbPointSerializer(serializers.Serializer):
    lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6)
    recorded_at = serializers.DateTimeField()


class BreadcrumbBatchSerializer(serializers.Serializer):
    points = BreadcrumbPointSerializer(many=True)

    def validate_points(self, value):
        if not value:
            raise serializers.ValidationError("A batch must contain at least one point.")
        return value
```

- [ ] **Step 6: Add the views**

Append to `services/transport-service/transport/views.py`:

```python
LIVE_POSITION_TTL_SECONDS = 60


def _live_key(tenant_id, route_id) -> str:
    """Tenant-namespaced, matching this service's existing seat-cache keys."""
    return f"transport:{tenant_id}:live:{route_id}"


class TripStartView(APIView):
    """POST /api/v1/transport/schedules/<id>/trips — begin a run."""

    permission_classes = [role_required("driver", "admin")]

    def post(self, request, schedule_id):
        try:
            schedule = BusSchedule.objects.get(pk=schedule_id)
        except BusSchedule.DoesNotExist:
            return fail("Schedule not found.", status=404)

        role = getattr(request.user, "role", None)
        if role != "admin" and str(schedule.driver_id) != str(request.user.id):
            return fail("You do not own this schedule.", status=403)

        if Trip.objects.filter(schedule=schedule, ended_at__isnull=True).exists():
            return fail("A trip is already active on this schedule.", status=400)

        trip = Trip.objects.create(
            tenant_id=request.user.tenant_id,
            schedule=schedule,
            driver_id=request.user.id,
        )
        return ok(TripSerializer(trip).data, message="Trip started.", status=201)


class TripEndView(APIView):
    """POST /api/v1/transport/trips/<id>/end — finish a run."""

    permission_classes = [role_required("driver", "admin")]

    def post(self, request, pk):
        try:
            trip = Trip.objects.get(pk=pk)
        except Trip.DoesNotExist:
            return fail("Trip not found.", status=404)

        role = getattr(request.user, "role", None)
        if role != "admin" and str(trip.driver_id) != str(request.user.id):
            return fail("You do not own this trip.", status=403)

        if trip.ended_at is not None:
            return fail("Trip has already ended.", status=400)

        trip.ended_at = timezone.now()
        trip.save(update_fields=["ended_at"])
        cache.delete(_live_key(request.user.tenant_id, trip.schedule.route_id))
        return ok(TripSerializer(trip).data, message="Trip ended.")


class BreadcrumbIngestView(APIView):
    """POST /api/v1/transport/trips/<id>/breadcrumbs — batched GPS samples.

    Batched rather than one-per-fix because the driver's app buffers points
    through tunnels and flushes them together. ``ignore_conflicts`` makes a
    replayed batch idempotent against the (trip, recorded_at) constraint.
    """

    permission_classes = [role_required("driver", "admin")]

    def post(self, request, pk):
        try:
            trip = Trip.objects.get(pk=pk)
        except Trip.DoesNotExist:
            return fail("Trip not found.", status=404)

        if str(trip.driver_id) != str(request.user.id):
            return fail("You do not own this trip.", status=403)

        serializer = BreadcrumbBatchSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid breadcrumb batch.", errors=serializer.errors, status=400)

        points = serializer.validated_data["points"]
        Breadcrumb.objects.bulk_create(
            [
                Breadcrumb(
                    tenant_id=request.user.tenant_id,
                    trip=trip,
                    lat=point["lat"],
                    lng=point["lng"],
                    recorded_at=point["recorded_at"],
                )
                for point in points
            ],
            ignore_conflicts=True,
        )

        latest = max(points, key=lambda p: p["recorded_at"])
        cache.set(
            _live_key(request.user.tenant_id, trip.schedule.route_id),
            {
                "lat": str(latest["lat"]),
                "lng": str(latest["lng"]),
                "recorded_at": latest["recorded_at"].isoformat(),
                "trip_id": str(trip.id),
            },
            timeout=LIVE_POSITION_TTL_SECONDS,
        )

        return ok({"accepted": len(points)}, message="Breadcrumbs recorded.", status=201)


class LivePositionView(APIView):
    """GET /api/v1/transport/routes/<id>/live — where the bus is right now.

    Served from Redis with a 60-second TTL: a position older than a minute is
    worse than no position, because a student would trust a stale dot.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, route_id):
        position = cache.get(_live_key(request.user.tenant_id, route_id))
        if position is None:
            return fail("No bus is currently running on this route.", status=404)
        return ok(position)
```

Add the missing imports at the top of the file: `from django.core.cache import cache`, `from django.utils import timezone`, `from rest_framework.permissions import IsAuthenticated`, plus `Breadcrumb`, `Trip`, `TripSerializer`, `BreadcrumbBatchSerializer`.

- [ ] **Step 7: Add the routes**

In `services/transport-service/transport/urls.py`, import the four views and add:

```python
    path("schedules/<uuid:schedule_id>/trips", TripStartView.as_view(), name="trip-start"),
    path("trips/<uuid:pk>/end", TripEndView.as_view(), name="trip-end"),
    path("trips/<uuid:pk>/breadcrumbs", BreadcrumbIngestView.as_view(), name="trip-breadcrumbs"),
    path("routes/<uuid:route_id>/live", LivePositionView.as_view(), name="route-live"),
```

- [ ] **Step 8: Migrate and run the tests**

Run: `cd services/transport-service && python manage.py makemigrations transport && python -m pytest transport/tests/ -v`
Expected: the 8 new tests PASS and every pre-existing transport test still PASSES

- [ ] **Step 9: Commit**

```bash
git add services/transport-service/
git commit -m "feat(transport): add driver trips, breadcrumb ingest, and live position"
```

---

## Task 3: Grievance status transitions

**Files:**
- Modify: `services/grievance-service/grievance/views.py`
- Modify: `services/grievance-service/grievance/urls.py`
- Create: `services/grievance-service/grievance/tests/test_status.py`

**Interfaces:**
- Consumes: `Ticket`, `TicketSerializer` (existing).
- Produces: `PATCH /api/v1/grievance/<uuid:ticket_id>/status` with body `{"status": "..."}`, warden/admin only, guarded by a legal-transition table.

- [ ] **Step 1: Read the current status choices**

Run: `grep -n "class Status" -A 10 services/grievance-service/grievance/models.py`
Record the exact `TextChoices` values. The transition table below must use those literals — correct it if they differ.

- [ ] **Step 2: Write the failing tests**

Create `services/grievance-service/grievance/tests/test_status.py`:

```python
"""Warden-driven grievance status transitions."""

import uuid

import pytest
from grievance.models import Ticket

pytestmark = pytest.mark.django_db

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()


def _client(tenant_id, role="warden", sub="WRD-001"):
    """Reuse this service's existing auth test helper."""
    from tests.helpers import auth_client  # noqa: PLC0415

    return auth_client(tenant_id=tenant_id, role=role, sub=sub)


def _ticket(tenant_id, status="open"):
    return Ticket.objects.create(
        tenant_id=tenant_id,
        category="hostel",
        description="Broken fan in room 12",
        raised_by="STU-001",
        status=status,
    )


def test_warden_resolves_an_open_ticket():
    ticket = _ticket(TENANT_A)
    client = _client(TENANT_A)

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "resolved"}, format="json"
    )

    assert response.status_code == 200
    ticket.refresh_from_db()
    assert ticket.status == "resolved"


def test_escalated_tickets_can_be_resolved():
    ticket = _ticket(TENANT_A, status="escalated")
    client = _client(TENANT_A)

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "resolved"}, format="json"
    )

    assert response.status_code == 200


def test_reopening_a_resolved_ticket_is_rejected():
    ticket = _ticket(TENANT_A, status="resolved")
    client = _client(TENANT_A)

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "open"}, format="json"
    )

    assert response.status_code == 400


def test_an_open_ticket_can_move_to_in_progress():
    ticket = _ticket(TENANT_A)
    client = _client(TENANT_A)

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "in_progress"}, format="json"
    )

    assert response.status_code == 200


def test_an_unknown_status_is_rejected():
    ticket = _ticket(TENANT_A)
    client = _client(TENANT_A)

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "banana"}, format="json"
    )

    assert response.status_code == 400


def test_students_cannot_change_status():
    ticket = _ticket(TENANT_A)
    client = _client(TENANT_A, role="student", sub="STU-001")

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "resolved"}, format="json"
    )

    assert response.status_code == 403


def test_a_warden_cannot_touch_another_tenants_ticket():
    ticket = _ticket(TENANT_A)
    client = _client(TENANT_B, sub="WRD-002")

    response = client.patch(
        f"/api/v1/grievance/{ticket.id}/status", {"status": "resolved"}, format="json"
    )

    assert response.status_code == 404
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd services/grievance-service && python -m pytest grievance/tests/test_status.py -v`
Expected: FAIL — 404, the route does not exist

- [ ] **Step 4: Add the view**

Append to `services/grievance-service/grievance/views.py`:

```python
#: Legal status moves, over Ticket.Status (open/escalated/in_progress/
#: resolved — there is no 'closed'). Resolution is terminal: a resolved
#: ticket never reopens, because the 7-day media purge (see the mobile
#: spec) is scheduled against its resolution time, and reopening would
#: promise evidence that is already on its way to being deleted.
_ALLOWED_STATUS_TRANSITIONS = {
    "open": {"escalated", "in_progress", "resolved"},
    "escalated": {"in_progress", "resolved"},
    "in_progress": {"resolved"},
    "resolved": set(),
}


class GrievanceStatusView(APIView):
    """PATCH /api/v1/grievance/<id>/status — warden moves a ticket forward."""

    permission_classes = [role_required("warden", "admin")]

    def patch(self, request, ticket_id):
        new_status = request.data.get("status")
        valid = set(_ALLOWED_STATUS_TRANSITIONS)
        if new_status not in valid:
            return fail(
                "Invalid status.",
                errors={"status": f"Must be one of {sorted(valid)}."},
                status=400,
            )

        # objects is tenant-scoped, so another tenant's ticket is simply
        # not found — no cross-tenant existence leak.
        try:
            ticket = Ticket.objects.get(id=ticket_id)
        except Ticket.DoesNotExist:
            return fail("Grievance not found.", status=404)

        if new_status not in _ALLOWED_STATUS_TRANSITIONS[ticket.status]:
            return fail(
                f"Cannot transition from '{ticket.status}' to '{new_status}'.",
                errors={"status": "Illegal transition."},
                status=400,
            )

        ticket.status = new_status
        ticket.save(update_fields=["status"])
        return ok(TicketSerializer(ticket).data, message="Status updated.")
```

Add `role_required` to the imports if it is not already present.

- [ ] **Step 5: Add the route**

In `services/grievance-service/grievance/urls.py`:

```python
    path(
        "grievance/<uuid:ticket_id>/status",
        GrievanceStatusView.as_view(),
        name="grievance-status",
    ),
```

- [ ] **Step 6: Run the tests**

Run: `cd services/grievance-service && python -m pytest grievance/tests/ -v`
Expected: the 7 new tests PASS and every pre-existing grievance test still PASSES

- [ ] **Step 7: Commit**

```bash
git add services/grievance-service/
git commit -m "feat(grievance): add warden status transitions with a legality guard"
```

---

## Task 4: Warden surface

**Files:**
- Create: `mobile/su-erp-app/src/lib/api/warden.ts`
- Create: `mobile/su-erp-app/src/features/warden/useWarden.ts`
- Create: `mobile/su-erp-app/app/(warden)/_layout.tsx`, `index.tsx`, `grievances.tsx`, `visitors.tsx`
- Create: `mobile/su-erp-app/src/lib/api/__tests__/warden.test.ts`
- Create: `shared/api-types/warden.ts`

**Interfaces:**
- Consumes: `request`, `enqueue`, `useConnectivity`, `Ticket`, `Allocation`, `Paginated`.
- Produces:
  - `fetchEscalatedTickets(): Promise<Paginated<Ticket>>`
  - `setTicketStatus(id: string, status: TicketStatus): Promise<Ticket | { queued: true }>` — queues offline
  - `fetchVisitors(all?: boolean): Promise<Paginated<VisitorLog>>`
  - `logVisitor(input: VisitorInput): Promise<VisitorLog | { queued: true }>` — queues offline
  - `checkoutVisitor(id: string): Promise<VisitorLog | { queued: true }>` — queues offline

- [ ] **Step 1: Add the shared types**

Create `shared/api-types/warden.ts`:

```ts
export interface VisitorLog {
  id: string;
  visitor_name: string;
  visiting_user_code: string;
  purpose: string;
  phone: string;
  logged_by: string;
  checked_in_at: string;
  checked_out_at: string | null;
}

export interface VisitorInput {
  visitor_name: string;
  visiting_user_code: string;
  purpose?: string;
  phone?: string;
}
```

Add `export * from './warden';` to `shared/api-types/index.ts`.

- [ ] **Step 2: Write the failing tests**

Create `mobile/su-erp-app/src/lib/api/__tests__/warden.test.ts`:

```ts
import { useConnectivity } from '../../net/connectivity';
import { checkoutVisitor, fetchVisitors, logVisitor, setTicketStatus } from '../warden';

jest.mock('../client', () => ({ request: jest.fn() }));
jest.mock('../../offline/queue', () => ({ enqueue: jest.fn(async () => ({ id: 'q1' })) }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));

const { request } = jest.requireMock('../client');
const { enqueue } = jest.requireMock('../../offline/queue');

beforeEach(() => {
  request.mockReset();
  enqueue.mockClear();
  useConnectivity.setState({ online: true });
});

test('fetchVisitors defaults to those still inside', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });
  await fetchVisitors();
  expect(request).toHaveBeenCalledWith('/api/v1/hostel/visitors');
});

test('fetchVisitors can ask for the full history', async () => {
  request.mockResolvedValue({ results: [], count: 0, page: 1, num_pages: 1 });
  await fetchVisitors(true);
  expect(request).toHaveBeenCalledWith('/api/v1/hostel/visitors?all=true');
});

test('logVisitor posts directly when online', async () => {
  request.mockResolvedValue({ id: 'v1' });
  await logVisitor({ visitor_name: 'Asha', visiting_user_code: 'STU-001' });
  expect(request).toHaveBeenCalled();
  expect(enqueue).not.toHaveBeenCalled();
});

test('logVisitor queues at the gate when offline', async () => {
  useConnectivity.setState({ online: false });

  const result = await logVisitor({ visitor_name: 'Asha', visiting_user_code: 'STU-001' });

  expect(enqueue).toHaveBeenCalledWith(
    '/api/v1/hostel/visitors',
    'POST',
    expect.objectContaining({ visitor_name: 'Asha' }),
  );
  expect(result).toEqual({ queued: true });
});

test('checkoutVisitor queues when offline', async () => {
  useConnectivity.setState({ online: false });

  await checkoutVisitor('v1');

  expect(enqueue).toHaveBeenCalledWith('/api/v1/hostel/visitors/v1/checkout', 'POST', {});
});

test('setTicketStatus patches the status endpoint when online', async () => {
  request.mockResolvedValue({ id: 't1', status: 'resolved' });

  await setTicketStatus('t1', 'resolved');

  expect(request).toHaveBeenCalledWith(
    '/api/v1/grievance/t1/status',
    expect.objectContaining({ method: 'PATCH' }),
  );
});

test('setTicketStatus queues when offline', async () => {
  useConnectivity.setState({ online: false });

  const result = await setTicketStatus('t1', 'resolved');

  expect(enqueue).toHaveBeenCalledWith('/api/v1/grievance/t1/status', 'PATCH', {
    status: 'resolved',
  });
  expect(result).toEqual({ queued: true });
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/warden.test.ts`
Expected: FAIL — module missing

- [ ] **Step 4: Write the API module**

Create `mobile/su-erp-app/src/lib/api/warden.ts`:

```ts
import type {
  Paginated,
  Ticket,
  TicketStatus,
  VisitorInput,
  VisitorLog,
} from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { enqueue } from '../offline/queue';
import { request } from './client';

/** Marker returned when a mutation was held for replay rather than sent. */
export type Queued = { queued: true };

function offline(): boolean {
  return !useConnectivity.getState().online;
}

export function fetchEscalatedTickets(): Promise<Paginated<Ticket>> {
  return request<Paginated<Ticket>>('/api/v1/grievance');
}

/**
 * Queueable: a warden closing tickets while walking a block loses signal
 * constantly, and a status change landing a few minutes late costs nothing.
 * The server's legal-transition guard rejects anything that no longer makes
 * sense by the time it arrives, and the queue drops those rather than
 * retrying (409/400 are terminal).
 */
export async function setTicketStatus(
  id: string,
  status: TicketStatus,
): Promise<Ticket | Queued> {
  if (offline()) {
    await enqueue(`/api/v1/grievance/${id}/status`, 'PATCH', { status });
    return { queued: true };
  }

  return request<Ticket>(`/api/v1/grievance/${id}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ status }),
  });
}

export function fetchVisitors(all = false): Promise<Paginated<VisitorLog>> {
  return request<Paginated<VisitorLog>>(`/api/v1/hostel/visitors${all ? '?all=true' : ''}`);
}

/** Queueable: the gate is the single worst-signal spot on most campuses. */
export async function logVisitor(input: VisitorInput): Promise<VisitorLog | Queued> {
  if (offline()) {
    await enqueue('/api/v1/hostel/visitors', 'POST', input);
    return { queued: true };
  }

  return request<VisitorLog>('/api/v1/hostel/visitors', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function checkoutVisitor(id: string): Promise<VisitorLog | Queued> {
  if (offline()) {
    await enqueue(`/api/v1/hostel/visitors/${id}/checkout`, 'POST', {});
    return { queued: true };
  }

  return request<VisitorLog>(`/api/v1/hostel/visitors/${id}/checkout`, { method: 'POST' });
}
```

- [ ] **Step 5: Write the hooks**

Create `mobile/su-erp-app/src/features/warden/useWarden.ts`:

```ts
import type { TicketStatus } from '@api-types/index';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  checkoutVisitor,
  fetchEscalatedTickets,
  fetchVisitors,
  logVisitor,
  setTicketStatus,
} from '@/lib/api/warden';

export const WARDEN_TICKETS_KEY = ['warden', 'tickets'];
export const VISITORS_KEY = ['warden', 'visitors'];

export function useWardenTickets() {
  return useQuery({ queryKey: WARDEN_TICKETS_KEY, queryFn: fetchEscalatedTickets });
}

export function useSetTicketStatus() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: TicketStatus }) =>
      setTicketStatus(id, status),
    onSuccess: () => client.invalidateQueries({ queryKey: WARDEN_TICKETS_KEY }),
  });
}

export function useVisitors() {
  return useQuery({ queryKey: VISITORS_KEY, queryFn: () => fetchVisitors() });
}

export function useLogVisitor() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: logVisitor,
    onSuccess: () => client.invalidateQueries({ queryKey: VISITORS_KEY }),
  });
}

export function useCheckoutVisitor() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: checkoutVisitor,
    onSuccess: () => client.invalidateQueries({ queryKey: VISITORS_KEY }),
  });
}
```

- [ ] **Step 6: Write the screens**

Create `mobile/su-erp-app/app/(warden)/_layout.tsx`:

```tsx
import { Ionicons } from '@expo/vector-icons';
import { Tabs } from 'expo-router';

export default function WardenLayout() {
  return (
    <Tabs screenOptions={{ tabBarActiveTintColor: '#1d4ed8' }}>
      <Tabs.Screen
        name="index"
        options={{
          title: 'Block',
          tabBarIcon: ({ color, size }) => <Ionicons name="business" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="grievances"
        options={{
          title: 'Grievances',
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="alert-circle" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="visitors"
        options={{
          title: 'Visitors',
          tabBarIcon: ({ color, size }) => <Ionicons name="people" color={color} size={size} />,
        }}
      />
    </Tabs>
  );
}
```

Create `mobile/su-erp-app/app/(warden)/grievances.tsx`:

```tsx
import { Alert, FlatList, Pressable, Text, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import {
  WARDEN_TICKETS_KEY,
  useSetTicketStatus,
  useWardenTickets,
} from '@/features/warden/useWarden';
import { cacheAge } from '@/lib/query/persister';

/** Escalated first — the ML escalation exists so wardens see these on top. */
const URGENCY_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

export default function WardenGrievances() {
  const { data, refetch, isRefetching } = useWardenTickets();
  const setStatus = useSetTicketStatus();

  const tickets = [...(data?.results ?? [])].sort((a, b) => {
    const escalated = Number(b.status === 'escalated') - Number(a.status === 'escalated');
    if (escalated !== 0) return escalated;
    return (URGENCY_RANK[a.urgency ?? 'low'] ?? 9) - (URGENCY_RANK[b.urgency ?? 'low'] ?? 9);
  });

  function resolve(id: string) {
    setStatus.mutate(
      { id, status: 'resolved' },
      {
        onSuccess: (result) => {
          if (result && 'queued' in result) {
            Alert.alert('Saved offline', 'This will sync when you reconnect.');
          }
        },
        onError: (e) => Alert.alert('Could not update', (e as Error).message),
      },
    );
  }

  return (
    <View style={{ flex: 1 }}>
      <OfflineBanner cachedAt={cacheAge(WARDEN_TICKETS_KEY)} />
      <FlatList
        data={tickets}
        keyExtractor={(t) => t.id}
        refreshing={isRefetching}
        onRefresh={refetch}
        ListEmptyComponent={<Text style={{ padding: 24 }}>No open grievances.</Text>}
        renderItem={({ item }) => (
          <View style={{ padding: 16, borderBottomWidth: 1, borderBottomColor: '#eee', gap: 6 }}>
            <Text style={{ fontWeight: '600', textTransform: 'capitalize' }}>{item.category}</Text>
            <Text style={{ color: '#666' }}>{item.description}</Text>
            <Text style={{ color: item.status === 'escalated' ? '#b00020' : '#666' }}>
              {item.status}
              {item.urgency ? ` · ${item.urgency}` : ''}
            </Text>
            {item.status !== 'resolved' ? (
              <Pressable
                onPress={() => resolve(item.id)}
                style={{
                  backgroundColor: '#166534',
                  borderRadius: 8,
                  padding: 10,
                  alignItems: 'center',
                }}
              >
                <Text style={{ color: '#fff', fontWeight: '600' }}>Mark resolved</Text>
              </Pressable>
            ) : null}
          </View>
        )}
      />
    </View>
  );
}
```

Create `mobile/su-erp-app/app/(warden)/visitors.tsx`:

```tsx
import { useState } from 'react';
import { Alert, FlatList, Pressable, Text, TextInput, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import {
  VISITORS_KEY,
  useCheckoutVisitor,
  useLogVisitor,
  useVisitors,
} from '@/features/warden/useWarden';
import { cacheAge } from '@/lib/query/persister';

export default function WardenVisitors() {
  const { data } = useVisitors();
  const log = useLogVisitor();
  const checkout = useCheckoutVisitor();
  const [name, setName] = useState('');
  const [studentCode, setStudentCode] = useState('');

  function submit() {
    log.mutate(
      { visitor_name: name, visiting_user_code: studentCode },
      {
        onSuccess: (result) => {
          setName('');
          setStudentCode('');
          if (result && 'queued' in result) {
            Alert.alert('Saved offline', 'This entry will sync when you reconnect.');
          }
        },
        onError: (e) => Alert.alert('Could not log visitor', (e as Error).message),
      },
    );
  }

  return (
    <View style={{ flex: 1 }}>
      <OfflineBanner cachedAt={cacheAge(VISITORS_KEY)} />

      <View style={{ padding: 16, gap: 8 }}>
        <TextInput
          placeholder="Visitor name"
          value={name}
          onChangeText={setName}
          style={{ borderWidth: 1, borderColor: '#ccc', borderRadius: 8, padding: 12 }}
        />
        <TextInput
          placeholder="Visiting (student code)"
          autoCapitalize="characters"
          value={studentCode}
          onChangeText={setStudentCode}
          style={{ borderWidth: 1, borderColor: '#ccc', borderRadius: 8, padding: 12 }}
        />
        <Pressable
          onPress={submit}
          disabled={!name || !studentCode}
          style={{ backgroundColor: '#1d4ed8', borderRadius: 8, padding: 14, alignItems: 'center' }}
        >
          <Text style={{ color: '#fff', fontWeight: '600' }}>Log entry</Text>
        </Pressable>
      </View>

      <FlatList
        data={data?.results ?? []}
        keyExtractor={(v) => v.id}
        ListHeaderComponent={
          <Text style={{ paddingHorizontal: 16, fontWeight: '600' }}>Currently inside</Text>
        }
        renderItem={({ item }) => (
          <View
            style={{
              flexDirection: 'row',
              alignItems: 'center',
              padding: 16,
              borderBottomWidth: 1,
              borderBottomColor: '#eee',
            }}
          >
            <View style={{ flex: 1 }}>
              <Text style={{ fontWeight: '600' }}>{item.visitor_name}</Text>
              <Text style={{ color: '#666' }}>
                → {item.visiting_user_code} ·{' '}
                {new Date(item.checked_in_at).toLocaleTimeString()}
              </Text>
            </View>
            <Pressable onPress={() => checkout.mutate(item.id)}>
              <Text style={{ color: '#1d4ed8', fontWeight: '600' }}>Check out</Text>
            </Pressable>
          </View>
        )}
      />
    </View>
  );
}
```

Replace `mobile/su-erp-app/app/(warden)/index.tsx` with a block roster reusing `fetchMyAllocations` from Phase 2's `lib/api/hostel.ts` (a warden's token returns the whole block rather than one student's row, since the endpoint filters by role). Render allocation rows grouped by room, with the offline banner at the top, following the same structure as the visitors screen above.

- [ ] **Step 7: Run the tests and typecheck**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/warden.test.ts && npx tsc --noEmit`
Expected: 7 tests PASS, no type errors

- [ ] **Step 8: Commit**

```bash
git add mobile/su-erp-app/src/lib/api/warden.ts mobile/su-erp-app/src/features/warden/ mobile/su-erp-app/app/\(warden\)/ shared/api-types/warden.ts
git commit -m "feat(mobile): add warden grievance queue and visitor log"
```

---

## Task 5: Driver surface

**Files:**
- Create: `mobile/su-erp-app/src/lib/api/driver.ts`
- Create: `mobile/su-erp-app/src/lib/device/location.ts`
- Create: `mobile/su-erp-app/src/features/driver/useDriver.ts`
- Create: `mobile/su-erp-app/app/(driver)/_layout.tsx`, `index.tsx`, `manifest.tsx`
- Create: `mobile/su-erp-app/src/lib/api/__tests__/driver.test.ts`
- Create: `shared/api-types/driver.ts`

**Interfaces:**
- Consumes: `request`, `enqueue`, `BusSchedule`, `Booking`, `Paginated`.
- Produces:
  - `fetchMySchedules(): Promise<Paginated<BusSchedule>>`
  - `startTrip(scheduleId: string): Promise<Trip>` — online-only (a trip must exist server-side before breadcrumbs can reference it)
  - `endTrip(tripId: string): Promise<Trip>`
  - `sendBreadcrumbs(tripId: string, points: BreadcrumbPoint[]): Promise<void>` — queues offline
  - `fetchManifest(scheduleId: string): Promise<Paginated<Booking>>`
  - `watchPosition(onPoint): Promise<() => void>` in `lib/device/location.ts`

- [ ] **Step 1: Add the shared types**

Create `shared/api-types/driver.ts`:

```ts
export interface Trip {
  id: string;
  schedule: string;
  driver_id: string;
  started_at: string;
  ended_at: string | null;
}

export interface BreadcrumbPoint {
  lat: string;
  lng: string;
  recorded_at: string;
}

export interface LivePosition {
  lat: string;
  lng: string;
  recorded_at: string;
  trip_id: string;
}
```

Add `export * from './driver';` to `shared/api-types/index.ts`.

- [ ] **Step 2: Write the failing tests**

Create `mobile/su-erp-app/src/lib/api/__tests__/driver.test.ts`:

```ts
import { useConnectivity } from '../../net/connectivity';
import { endTrip, sendBreadcrumbs, startTrip } from '../driver';
import { OfflineError } from '../finance';

jest.mock('../client', () => ({ request: jest.fn() }));
jest.mock('../../offline/queue', () => ({ enqueue: jest.fn(async () => ({ id: 'q1' })) }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));

const { request } = jest.requireMock('../client');
const { enqueue } = jest.requireMock('../../offline/queue');

const POINT = { lat: '12.97', lng: '77.59', recorded_at: '2026-08-04T08:01:00Z' };

beforeEach(() => {
  request.mockReset();
  enqueue.mockClear();
  useConnectivity.setState({ online: true });
});

test('startTrip posts to the schedule trips endpoint', async () => {
  request.mockResolvedValue({ id: 'trip-1' });

  await startTrip('sched-1');

  expect(request).toHaveBeenCalledWith(
    '/api/v1/transport/schedules/sched-1/trips',
    expect.objectContaining({ method: 'POST' }),
  );
});

test('startTrip refuses to run offline', async () => {
  useConnectivity.setState({ online: false });
  await expect(startTrip('sched-1')).rejects.toBeInstanceOf(OfflineError);
});

test('endTrip posts to the end endpoint', async () => {
  request.mockResolvedValue({ id: 'trip-1', ended_at: 'now' });

  await endTrip('trip-1');

  expect(request).toHaveBeenCalledWith(
    '/api/v1/transport/trips/trip-1/end',
    expect.objectContaining({ method: 'POST' }),
  );
});

test('sendBreadcrumbs posts the batch when online', async () => {
  request.mockResolvedValue({ accepted: 1 });

  await sendBreadcrumbs('trip-1', [POINT]);

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body.points).toEqual([POINT]);
  expect(enqueue).not.toHaveBeenCalled();
});

test('sendBreadcrumbs queues the batch through a tunnel', async () => {
  useConnectivity.setState({ online: false });

  await sendBreadcrumbs('trip-1', [POINT]);

  expect(enqueue).toHaveBeenCalledWith('/api/v1/transport/trips/trip-1/breadcrumbs', 'POST', {
    points: [POINT],
  });
  expect(request).not.toHaveBeenCalled();
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/driver.test.ts`
Expected: FAIL — module missing

- [ ] **Step 4: Write the API module**

Create `mobile/su-erp-app/src/lib/api/driver.ts`:

```ts
import type {
  Booking,
  BreadcrumbPoint,
  BusSchedule,
  Paginated,
  Trip,
} from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { enqueue } from '../offline/queue';
import { request } from './client';
import { OfflineError } from './finance';

function offline(): boolean {
  return !useConnectivity.getState().online;
}

export function fetchMySchedules(): Promise<Paginated<BusSchedule>> {
  return request<Paginated<BusSchedule>>('/api/v1/transport/schedules/mine');
}

/**
 * Online-only: breadcrumbs are addressed to a trip id that only the server
 * can mint, so a queued start would leave every later point with nowhere to
 * go. The driver taps this at the depot, where signal exists.
 */
export async function startTrip(scheduleId: string): Promise<Trip> {
  if (offline()) throw new OfflineError('Connect to the network to start your trip.');
  return request<Trip>(`/api/v1/transport/schedules/${scheduleId}/trips`, { method: 'POST' });
}

export async function endTrip(tripId: string): Promise<Trip> {
  if (offline()) throw new OfflineError('Connect to the network to end your trip.');
  return request<Trip>(`/api/v1/transport/trips/${tripId}/end`, { method: 'POST' });
}

/**
 * Queueable, and the reason the queue exists. A bus spends minutes at a
 * time with no signal; points are buffered with their on-device timestamps
 * and replayed as a batch, so the trail keeps its real shape instead of
 * collapsing into the moment the signal returned.
 */
export async function sendBreadcrumbs(
  tripId: string,
  points: BreadcrumbPoint[],
): Promise<void> {
  const path = `/api/v1/transport/trips/${tripId}/breadcrumbs`;

  if (offline()) {
    await enqueue(path, 'POST', { points });
    return;
  }

  await request<void>(path, { method: 'POST', body: JSON.stringify({ points }) });
}

export function fetchManifest(scheduleId: string): Promise<Paginated<Booking>> {
  return request<Paginated<Booking>>(`/api/v1/transport/schedules/${scheduleId}/bookings`);
}
```

- [ ] **Step 5: Write the location module**

Create `mobile/su-erp-app/src/lib/device/location.ts`:

```ts
import * as Location from 'expo-location';

import type { BreadcrumbPoint } from '@api-types/index';

/** How often the driver's device samples position while a trip is running. */
export const BREADCRUMB_INTERVAL_MS = 15_000;

export async function requestPermission(): Promise<boolean> {
  const { status } = await Location.requestForegroundPermissionsAsync();
  return status === 'granted';
}

/**
 * Streams position while a trip is active. The timestamp comes from the
 * device, not the server, because these points are frequently delivered
 * late in a batch — see sendBreadcrumbs.
 */
export async function watchPosition(
  onPoint: (point: BreadcrumbPoint) => void,
): Promise<() => void> {
  const subscription = await Location.watchPositionAsync(
    {
      accuracy: Location.Accuracy.Balanced,
      timeInterval: BREADCRUMB_INTERVAL_MS,
      distanceInterval: 25,
    },
    (position) => {
      onPoint({
        lat: position.coords.latitude.toFixed(6),
        lng: position.coords.longitude.toFixed(6),
        recorded_at: new Date(position.timestamp).toISOString(),
      });
    },
  );

  return () => subscription.remove();
}
```

Install it: `cd mobile/su-erp-app && npx expo install expo-location`

- [ ] **Step 6: Write the hook**

Create `mobile/su-erp-app/src/features/driver/useDriver.ts`:

```ts
import type { BreadcrumbPoint, Trip } from '@api-types/index';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';

import { endTrip, fetchMySchedules, sendBreadcrumbs, startTrip } from '@/lib/api/driver';
import { requestPermission, watchPosition } from '@/lib/device/location';

export const SCHEDULES_KEY = ['driver', 'schedules'];

export function useMySchedules() {
  return useQuery({ queryKey: SCHEDULES_KEY, queryFn: fetchMySchedules });
}

/**
 * Owns the active trip and the GPS stream that belongs to it. Points are
 * buffered and flushed in batches rather than sent one at a time — one
 * request every 15 seconds would drain a driver's battery over a full route.
 */
export function useActiveTrip() {
  const [trip, setTrip] = useState<Trip | null>(null);
  const buffer = useRef<BreadcrumbPoint[]>([]);
  const stopWatch = useRef<(() => void) | null>(null);

  const flush = useCallback(async (tripId: string) => {
    if (buffer.current.length === 0) return;
    const points = buffer.current;
    buffer.current = [];
    await sendBreadcrumbs(tripId, points);
  }, []);

  const start = useMutation({
    mutationFn: async (scheduleId: string) => {
      const granted = await requestPermission();
      if (!granted) throw new Error('Location permission is required to run a trip.');

      const started = await startTrip(scheduleId);
      stopWatch.current = await watchPosition((point) => buffer.current.push(point));
      setTrip(started);
      return started;
    },
  });

  const end = useMutation({
    mutationFn: async () => {
      if (!trip) throw new Error('No active trip.');
      stopWatch.current?.();
      stopWatch.current = null;
      await flush(trip.id);
      const ended = await endTrip(trip.id);
      setTrip(null);
      return ended;
    },
  });

  useEffect(() => {
    if (!trip) return undefined;
    const timer = setInterval(() => void flush(trip.id), 30_000);
    return () => clearInterval(timer);
  }, [trip, flush]);

  useEffect(() => () => stopWatch.current?.(), []);

  return { trip, start, end };
}
```

- [ ] **Step 7: Write the screens**

Create `mobile/su-erp-app/app/(driver)/_layout.tsx` (same `Tabs` shape as the warden layout, with `index` titled "Trip" and `manifest` titled "Riders").

Create `mobile/su-erp-app/app/(driver)/index.tsx`:

```tsx
import { Alert, Pressable, ScrollView, Text, View } from 'react-native';

import { OfflineBanner } from '@/components/OfflineBanner';
import { SCHEDULES_KEY, useActiveTrip, useMySchedules } from '@/features/driver/useDriver';
import { cacheAge } from '@/lib/query/persister';

export default function DriverTrip() {
  const { data } = useMySchedules();
  const { trip, start, end } = useActiveTrip();

  return (
    <ScrollView style={{ flex: 1 }}>
      <OfflineBanner cachedAt={cacheAge(SCHEDULES_KEY)} />

      {trip ? (
        <View style={{ padding: 16, gap: 12, backgroundColor: '#dcfce7' }}>
          <Text style={{ fontSize: 18, fontWeight: '600' }}>Trip running</Text>
          <Text>Started {new Date(trip.started_at).toLocaleTimeString()}</Text>
          <Pressable
            onPress={() =>
              end.mutate(undefined, {
                onError: (e) => Alert.alert('Could not end trip', (e as Error).message),
              })
            }
            style={{ backgroundColor: '#b00020', borderRadius: 8, padding: 14, alignItems: 'center' }}
          >
            <Text style={{ color: '#fff', fontWeight: '600' }}>End trip</Text>
          </Pressable>
        </View>
      ) : (
        <View style={{ padding: 16, gap: 12 }}>
          <Text style={{ fontSize: 18, fontWeight: '600' }}>Today's schedules</Text>
          {(data?.results ?? []).map((schedule) => (
            <View key={schedule.id} style={{ gap: 6 }}>
              <Text>
                Bus {schedule.bus_no} · {new Date(schedule.departure_time).toLocaleTimeString()}
              </Text>
              <Pressable
                onPress={() =>
                  start.mutate(schedule.id, {
                    onError: (e) => Alert.alert('Could not start', (e as Error).message),
                  })
                }
                style={{
                  backgroundColor: '#166534',
                  borderRadius: 8,
                  padding: 12,
                  alignItems: 'center',
                }}
              >
                <Text style={{ color: '#fff', fontWeight: '600' }}>Start trip</Text>
              </Pressable>
            </View>
          ))}
        </View>
      )}
    </ScrollView>
  );
}
```

Create `mobile/su-erp-app/app/(driver)/manifest.tsx` listing `fetchManifest(scheduleId)` results — one row per booking showing `seat_no` and `student_user_code`, with the offline banner at the top. Pick the schedule from `useMySchedules()` the same way the trip screen does.

- [ ] **Step 8: Run the tests and typecheck**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/driver.test.ts && npx tsc --noEmit`
Expected: 5 tests PASS, no type errors

- [ ] **Step 9: Commit**

```bash
git add mobile/su-erp-app/src/lib/api/driver.ts mobile/su-erp-app/src/lib/device/location.ts mobile/su-erp-app/src/features/driver/ mobile/su-erp-app/app/\(driver\)/ shared/api-types/driver.ts
git commit -m "feat(mobile): add driver trip control with buffered GPS breadcrumbs"
```

---

## Task 6: Canteen-owner surface

**Files:**
- Create: `mobile/su-erp-app/src/lib/api/owner.ts`
- Create: `mobile/su-erp-app/src/features/owner/useOwner.ts`
- Create: `mobile/su-erp-app/app/(canteen-owner)/_layout.tsx`, `index.tsx`, `menu.tsx`
- Create: `mobile/su-erp-app/src/lib/api/__tests__/owner.test.ts`

**Interfaces:**
- Consumes: `request`, `enqueue`, `MenuItem`, `Order`, `OrderStatus`, `Paginated`.
- Produces:
  - `fetchOrderBoard(): Promise<Paginated<Order>>`
  - `advanceOrder(id: string, status: OrderStatus): Promise<Order | Queued>` — queues offline
  - `setItemAvailability(id: string, available: boolean): Promise<MenuItem>`
  - `setItemPrice(id: string, price: string): Promise<MenuItem>`
  - `NEXT_STATUS: Record<OrderStatus, OrderStatus | null>` — mirrors the server's transition table

- [ ] **Step 1: Confirm the server's transition table**

Run: `grep -n "_ALLOWED_TRANSITIONS" -A 10 services/canteen-service/canteen/views.py`
Record it exactly. The client's `NEXT_STATUS` must be a subset — the app should never offer a button the server will reject.

- [ ] **Step 2: Write the failing tests**

Create `mobile/su-erp-app/src/lib/api/__tests__/owner.test.ts`:

```ts
import { useConnectivity } from '../../net/connectivity';
import { NEXT_STATUS, advanceOrder, setItemAvailability } from '../owner';

jest.mock('../client', () => ({ request: jest.fn() }));
jest.mock('../../offline/queue', () => ({ enqueue: jest.fn(async () => ({ id: 'q1' })) }));
jest.mock('@react-native-community/netinfo', () => ({ addEventListener: jest.fn(() => () => {}) }));

const { request } = jest.requireMock('../client');
const { enqueue } = jest.requireMock('../../offline/queue');

beforeEach(() => {
  request.mockReset();
  enqueue.mockClear();
  useConnectivity.setState({ online: true });
});

test('the client transition table matches the kitchen flow', () => {
  expect(NEXT_STATUS.placed).toBe('preparing');
  expect(NEXT_STATUS.preparing).toBe('ready');
  expect(NEXT_STATUS.ready).toBe('completed');
  expect(NEXT_STATUS.completed).toBeNull();
  expect(NEXT_STATUS.cancelled).toBeNull();
});

test('advanceOrder patches the status endpoint when online', async () => {
  request.mockResolvedValue({ id: 'o1', status: 'preparing' });

  await advanceOrder('o1', 'preparing');

  expect(request).toHaveBeenCalledWith(
    '/api/v1/orders/o1/status/',
    expect.objectContaining({ method: 'PATCH' }),
  );
});

test('advanceOrder queues in the basement kitchen', async () => {
  useConnectivity.setState({ online: false });

  const result = await advanceOrder('o1', 'ready');

  expect(enqueue).toHaveBeenCalledWith('/api/v1/orders/o1/status/', 'PATCH', { status: 'ready' });
  expect(result).toEqual({ queued: true });
});

test('setItemAvailability patches the menu item', async () => {
  request.mockResolvedValue({ id: 'm1', available: false });

  await setItemAvailability('m1', false);

  const body = JSON.parse(request.mock.calls[0][1].body);
  expect(body).toEqual({ available: false });
});
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd mobile/su-erp-app && npx jest src/lib/api/__tests__/owner.test.ts`
Expected: FAIL — module missing

- [ ] **Step 4: Write the API module**

Create `mobile/su-erp-app/src/lib/api/owner.ts`:

```ts
import type { MenuItem, Order, OrderStatus, Paginated } from '@api-types/index';

import { useConnectivity } from '../net/connectivity';
import { enqueue } from '../offline/queue';
import { request } from './client';
import type { Queued } from './warden';

/**
 * The one forward move offered for each state, mirroring the server's
 * _ALLOWED_TRANSITIONS. Keeping this a strict subset means the app never
 * shows a button whose request the server will reject.
 */
export const NEXT_STATUS: Record<OrderStatus, OrderStatus | null> = {
  placed: 'preparing',
  preparing: 'ready',
  ready: 'completed',
  completed: null,
  cancelled: null,
};

export function fetchOrderBoard(): Promise<Paginated<Order>> {
  return request<Paginated<Order>>('/api/v1/orders/');
}

/**
 * Queueable: kitchens sit in basements. If two operators advance the same
 * order, the server's legal-transition guard rejects the loser with a 400
 * and the queue drops it rather than retrying — the state the kitchen
 * actually reached wins.
 */
export async function advanceOrder(id: string, status: OrderStatus): Promise<Order | Queued> {
  const path = `/api/v1/orders/${id}/status/`;

  if (!useConnectivity.getState().online) {
    await enqueue(path, 'PATCH', { status });
    return { queued: true };
  }

  return request<Order>(path, { method: 'PATCH', body: JSON.stringify({ status }) });
}

export function setItemAvailability(id: string, available: boolean): Promise<MenuItem> {
  return request<MenuItem>(`/api/v1/menu-items/${id}/`, {
    method: 'PATCH',
    body: JSON.stringify({ available }),
  });
}

export function setItemPrice(id: string, price: string): Promise<MenuItem> {
  return request<MenuItem>(`/api/v1/menu-items/${id}/`, {
    method: 'PATCH',
    body: JSON.stringify({ price }),
  });
}
```

- [ ] **Step 5: Write the hooks**

Create `mobile/su-erp-app/src/features/owner/useOwner.ts`:

```ts
import type { OrderStatus } from '@api-types/index';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { fetchMenu } from '@/lib/api/canteen';
import { advanceOrder, fetchOrderBoard, setItemAvailability, setItemPrice } from '@/lib/api/owner';

export const BOARD_KEY = ['owner', 'orders'];
export const OWNER_MENU_KEY = ['owner', 'menu'];

export function useOrderBoard() {
  return useQuery({
    queryKey: BOARD_KEY,
    queryFn: fetchOrderBoard,
    // The board is a live work surface — students place orders while it is
    // open, so it polls rather than waiting for a pull-to-refresh.
    refetchInterval: 10_000,
  });
}

export function useAdvanceOrder() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: OrderStatus }) => advanceOrder(id, status),
    onSuccess: () => client.invalidateQueries({ queryKey: BOARD_KEY }),
  });
}

export function useOwnerMenu() {
  return useQuery({ queryKey: OWNER_MENU_KEY, queryFn: fetchMenu });
}

export function useSetAvailability() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, available }: { id: string; available: boolean }) =>
      setItemAvailability(id, available),
    onSuccess: () => client.invalidateQueries({ queryKey: OWNER_MENU_KEY }),
  });
}

export function useSetPrice() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, price }: { id: string; price: string }) => setItemPrice(id, price),
    onSuccess: () => client.invalidateQueries({ queryKey: OWNER_MENU_KEY }),
  });
}
```

- [ ] **Step 6: Write the order board screen**

Create `mobile/su-erp-app/app/(canteen-owner)/index.tsx`:

```tsx
import type { Order, OrderStatus } from '@api-types/index';
import { Alert, ScrollView, Text, View } from 'react-native';
import { Pressable } from 'react-native';

import { Money } from '@/components/Money';
import { OfflineBanner } from '@/components/OfflineBanner';
import { BOARD_KEY, useAdvanceOrder, useOrderBoard } from '@/features/owner/useOwner';
import { NEXT_STATUS } from '@/lib/api/owner';
import { cacheAge } from '@/lib/query/persister';

const LANES: OrderStatus[] = ['placed', 'preparing', 'ready'];

export default function OrderBoard() {
  const { data } = useOrderBoard();
  const advance = useAdvanceOrder();

  const byLane = (lane: OrderStatus): Order[] =>
    (data?.results ?? []).filter((order) => order.status === lane);

  function advanceTo(order: Order) {
    const next = NEXT_STATUS[order.status];
    if (!next) return;

    advance.mutate(
      { id: order.id, status: next },
      {
        onSuccess: (result) => {
          if (result && 'queued' in result) {
            Alert.alert('Saved offline', 'This will sync when you reconnect.');
          }
        },
        onError: (e) => Alert.alert('Could not update', (e as Error).message),
      },
    );
  }

  return (
    <ScrollView style={{ flex: 1 }}>
      <OfflineBanner cachedAt={cacheAge(BOARD_KEY)} />

      {LANES.map((lane) => (
        <View key={lane} style={{ padding: 16, gap: 8 }}>
          <Text style={{ fontSize: 16, fontWeight: '600', textTransform: 'capitalize' }}>
            {lane} ({byLane(lane).length})
          </Text>

          {byLane(lane).map((order) => (
            <View
              key={order.id}
              style={{ padding: 12, borderRadius: 8, backgroundColor: '#f3f4f6', gap: 6 }}
            >
              <Text style={{ fontWeight: '600' }}>{order.student_user_code}</Text>
              {order.items.map((item) => (
                <Text key={item.id} style={{ color: '#555' }}>
                  {item.quantity}× {item.name}
                </Text>
              ))}
              <Money value={order.total} />
              <Pressable
                onPress={() => advanceTo(order)}
                style={{
                  backgroundColor: '#1d4ed8',
                  borderRadius: 6,
                  padding: 10,
                  alignItems: 'center',
                }}
              >
                <Text style={{ color: '#fff', fontWeight: '600' }}>
                  Mark {NEXT_STATUS[order.status]}
                </Text>
              </Pressable>
            </View>
          ))}
        </View>
      ))}
    </ScrollView>
  );
}
```

- [ ] **Step 7: Write the menu management screen and layout**

Create `mobile/su-erp-app/app/(canteen-owner)/_layout.tsx` (same `Tabs` shape as the warden layout, with `index` titled "Orders" and `menu` titled "Menu").

Create `mobile/su-erp-app/app/(canteen-owner)/menu.tsx` listing `useOwnerMenu()` results. Each row shows the name, an editable price `TextInput` that calls `useSetPrice()` on blur, and a `Switch` bound to `useSetAvailability()`. Put the offline banner at the top and keep the same row structure as the warden visitors screen.

- [ ] **Step 8: Run the tests and typecheck**

Run: `cd mobile/su-erp-app && npx jest && npx tsc --noEmit`
Expected: every test PASSES, no type errors

- [ ] **Step 9: Commit**

```bash
git add mobile/su-erp-app/src/lib/api/owner.ts mobile/su-erp-app/src/features/owner/ mobile/su-erp-app/app/\(canteen-owner\)/
git commit -m "feat(mobile): add canteen owner order board and menu management"
```

---

## Task 7: End-to-end verification of the field roles

**Files:**
- Modify: `docs/RUNBOOK-mobile.md`

- [ ] **Step 1: Run the full backend suite**

Run:
```bash
cd services/hostel-service && python -m pytest -q
cd ../transport-service && python -m pytest -q
cd ../grievance-service && python -m pytest -q
```
Expected: every suite passes, including the pre-existing tests in each.

- [ ] **Step 2: Bring the stack up**

Run:
```bash
docker compose -f infra/docker-compose.yml up -d postgres redis rabbitmq \
  auth-service hostel-service finance-service canteen-service \
  transport-service grievance-service notification-service gateway
docker compose -f infra/docker-compose.yml exec hostel-service python manage.py migrate
docker compose -f infra/docker-compose.yml exec transport-service python manage.py migrate
```

- [ ] **Step 3: Walk each role on a device**

Signed in as a **warden**: log a visitor, check them out, resolve an escalated grievance.
Signed in as a **driver**: start a trip, confirm the position updates, view the manifest, end the trip.
Signed in as a **canteen owner**: advance an order through placed → preparing → ready → completed.

- [ ] **Step 4: Verify the queue under airplane mode**

With each role signed in, enable airplane mode and perform its queueable mutation (visitor entry, breadcrumbs, order advance). Confirm the "Saved offline" alert, then disable airplane mode and confirm the change lands within a few seconds.

For the driver specifically: run a trip, put the phone in airplane mode for two minutes while moving, then restore signal. Confirm via
`curl -s http://localhost:8080/api/v1/transport/routes/<route-id>/live -H "Authorization: Bearer <token>"`
that the position advances and the breadcrumb trail has points spanning the gap rather than clustered at the reconnect instant.

- [ ] **Step 5: Record the results**

Append a "Phase 3 — field roles" section to `docs/RUNBOOK-mobile.md` with the commands above and their observed outcomes, including the breadcrumb-gap check.

- [ ] **Step 6: Commit**

```bash
git add docs/RUNBOOK-mobile.md
git commit -m "docs: record verified warden, driver, and canteen-owner flows"
```

---

## Out of scope for Phase 3

- QR e-pass, scanning, geofenced attendance, camera grievance, widgets, document vault — **Phase 4**
- The student-facing live bus map (this phase ships the driver's broadcast and the `/live` endpoint; the map UI arrives in Phase 4 with the rest of the hardware work)
- Push notifications — the `push-channel` consumer in `notification-service`
- Warden leave-request approvals (the backend endpoint exists; add it to the warden shell alongside the roster if time allows)
