# Optional-Fee Allocation, Payment Due-Date Expiry, and One-Seat-Per-Student Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a warden allocate a room with no fee at all (confirms immediately, no invoice), require an explicit due date whenever a fee IS used, replace the fixed 30-minute pending-allocation timeout with that due date, and enforce that a student can hold at most one active (pending/confirmed) allocation across any room.

**Architecture:** Changes span hostel-service (`AllocateView`, `AllocateBulkView`, `ApproveRoomRequestView`, `create_allocation`, the CSV template/parser, `release_stale_pending_allocations`, a new `Allocation.due_date` field and a new conditional `UniqueConstraint`) and finance-service (`handle_allocation_requested` consumer, a new `Invoice.due_date` field, deletion of the `HOSTEL_FEE_AMOUNT` hardcoded fallback). No new services, no new event types — the no-fee path is handled synchronously inside `create_allocation()` without publishing `hostel.allocation.requested` at all, since finance-service is the only consumer of that event and has nothing to do when there's no fee.

**Tech Stack:** Django 5 + DRF (both services), pytest + `rest_framework.test.APIClient`.

## Global Constraints

- Every endpoint uses `ok`/`fail` from `suerp_common.envelope` and `role_required(...)` from `suerp_common.permissions` — never raw DRF `Response` or hand-rolled role checks.
- State change + `publish_event` stay in the same `transaction.atomic()` block wherever both happen (transactional outbox guarantee) — matches every existing handler in this codebase.
- hostel-service views use `Room.objects`/`Allocation.objects` (auto-scoped `TenantManager`, real request context). Consumers (`hostel/consumers.py`, `billing/consumers.py`) use `all_objects` with an explicit `tenant_id` (no ambient tenant in a standalone consumer process) — this is unchanged, just don't mix the two up when editing either file.
- `due_date` is a `DateField` (not `DateTimeField`) end to end — a warden picks a calendar date, not a time of day. The expiry check in `release_stale_pending_allocations` treats "due_date has passed" as `due_date < timezone.now().date()`.
- Existing hostel-service (72 tests) and finance-service (40 tests) suites must keep passing throughout. Run via:
  - hostel-service: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest -q`
  - finance-service: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/finance" finance-service pytest -q`
  (pgbouncer can't create databases — tests must bypass it and hit `suerp-postgres` directly, same as the previous session's fix.)
- After backend changes: rebuild + restart the affected container(s) for changes to take effect — the images are NOT volume-mounted, so `docker compose exec` against a running container runs stale code until rebuilt: `docker compose -f infra/docker-compose.yml build <service> && docker compose -f infra/docker-compose.yml up -d <service>`.
- New model fields require `python manage.py makemigrations` run inside the container (`docker compose -f infra/docker-compose.yml exec <service> python manage.py makemigrations <app>`) — migrations do not auto-generate, only auto-*apply* on container start.

---

## Task 1: `Allocation.due_date` field + one-seat-per-student constraint

**Files:**
- Modify: `services/hostel-service/hostel/models.py:64-92` (`Allocation`)
- Create: `services/hostel-service/hostel/migrations/0002_allocation_due_date_and_one_seat_constraint.py` (generated, not hand-written)
- Create: `services/hostel-service/hostel/tests/test_allocation_constraints.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `Allocation.due_date` (nullable `DateField`) and a DB-level `UniqueConstraint` named `allocation_one_active_per_student` on `(tenant_id, student_user_code)` scoped to `status__in=["pending", "confirmed"]`. Task 2 (`create_allocation`) catches the `IntegrityError` this raises.

- [ ] **Step 1: Write the failing test**

Create `services/hostel-service/hostel/tests/test_allocation_constraints.py`:

```python
"""DB-level constraints on Allocation:
- allocation_one_active_per_student: a student can hold at most one
  pending/confirmed allocation at a time, across any room. A released
  allocation doesn't count, so the student can be reallocated later.
"""

import uuid

import pytest
from django.db import IntegrityError
from hostel.models import Allocation

pytestmark = pytest.mark.django_db

from hostel.tests.test_allocate import _make_room  # noqa: E402


def _make_allocation(tenant_id, room, student_user_code, status="pending"):
    return Allocation.all_objects.create(
        tenant_id=tenant_id,
        room=room,
        student_user_code=student_user_code,
        status=status,
    )


def test_rejects_second_pending_allocation_for_same_student():
    tenant_id = uuid.uuid4()
    room_a = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    room_b = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="102")
    _make_allocation(tenant_id, room_a, "STU001", status="pending")

    with pytest.raises(IntegrityError):
        _make_allocation(tenant_id, room_b, "STU001", status="pending")


def test_rejects_confirmed_and_pending_combination():
    tenant_id = uuid.uuid4()
    room_a = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    room_b = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="102")
    _make_allocation(tenant_id, room_a, "STU001", status="confirmed")

    with pytest.raises(IntegrityError):
        _make_allocation(tenant_id, room_b, "STU001", status="pending")


def test_allows_new_allocation_after_release():
    tenant_id = uuid.uuid4()
    room_a = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    room_b = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="102")
    _make_allocation(tenant_id, room_a, "STU001", status="released")

    # Should not raise.
    _make_allocation(tenant_id, room_b, "STU001", status="pending")


def test_due_date_field_defaults_to_none():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    allocation = _make_allocation(tenant_id, room, "STU001", status="pending")

    assert allocation.due_date is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_allocation_constraints.py -v`
Expected: `test_rejects_second_pending_allocation_for_same_student` and `test_rejects_confirmed_and_pending_combination` FAIL (no `IntegrityError` raised — the constraint doesn't exist yet); `test_due_date_field_defaults_to_none` FAILS with `AttributeError: 'Allocation' object has no attribute 'due_date'`.

- [ ] **Step 3: Add the field and constraint to the model**

In `services/hostel-service/hostel/models.py`, modify the `Allocation` class:

```python
class Allocation(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        CONFIRMED = "confirmed", "Confirmed"
        RELEASED = "released", "Released"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="allocations")
    # Reference to student-service's Student (auth-service's user_code).
    student_user_code = models.CharField(max_length=30)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    allocated_on = models.DateTimeField(auto_now_add=True)
    vacated_on = models.DateField(null=True, blank=True)
    # Filled in when finance-service emits finance.invoice.created, for
    # correlating this allocation with its hostel-fee invoice. Bare UUID
    # (finance-service owns the Invoice row in its own database).
    invoice_id = models.UUIDField(null=True, blank=True)
    # Payment deadline, set only when this allocation carries a fee (see
    # hostel/services.py create_allocation). release_stale_pending_allocations
    # (hostel/tasks.py) releases a pending allocation once this date passes
    # unpaid. Null for direct/no-fee allocations, which are never pending in
    # the first place (confirmed synchronously at creation).
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="allocation_tenant_status"),
            models.Index(
                fields=["tenant_id", "student_user_code"], name="allocation_tenant_student"
            ),
        ]
        constraints = [
            # A student can hold at most ONE active (pending or confirmed)
            # allocation at a time, across any room. Scoped to these two
            # statuses so a released allocation never blocks a later
            # reallocation for the same student — mirrors the existing
            # RoomRequest.roomrequest_one_pending_per_student_room pattern.
            models.UniqueConstraint(
                fields=["tenant_id", "student_user_code"],
                condition=models.Q(status__in=["pending", "confirmed"]),
                name="allocation_one_active_per_student",
            ),
        ]

    def __str__(self):
        return f"Allocation {self.id} ({self.status})"
```

- [ ] **Step 4: Generate the migration**

Run: `docker compose -f infra/docker-compose.yml exec hostel-service python manage.py makemigrations hostel`
Expected: creates `hostel/migrations/0002_<name>.py` adding the `due_date` field and the `allocation_one_active_per_student` constraint. Rename the generated file to `0002_allocation_due_date_and_one_seat_constraint.py` if Django's auto-generated name differs, for clarity (the migration's internal `dependencies`/`operations` don't need editing, just optionally the filename — skip the rename if the auto-generated name is already `0002_*` and reasonably descriptive).

- [ ] **Step 5: Rebuild and restart hostel-service, run tests to verify they pass**

Run:
```bash
docker compose -f infra/docker-compose.yml build hostel-service
docker compose -f infra/docker-compose.yml up -d hostel-service
docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_allocation_constraints.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 6: Run the full hostel-service suite to confirm no regressions**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest -q`
Expected: all tests pass (72 existing + 4 new = 76, 0 failures). If any existing test creates two allocations for the same `student_user_code` without releasing the first (check `test_saga.py`, `test_room_request_approval.py`, `test_allocate_bulk.py` for this pattern), fix that test's fixture data to use distinct student codes rather than relaxing the constraint — the constraint is the point of this task.

- [ ] **Step 7: Commit**

```bash
git add services/hostel-service/hostel/models.py services/hostel-service/hostel/migrations/ services/hostel-service/hostel/tests/test_allocation_constraints.py
git commit -m "feat(hostel-service): add Allocation.due_date, enforce one active allocation per student"
```

---

## Task 2: `create_allocation` — synchronous no-fee confirm, mandatory due_date-with-fee, constraint handling

**Files:**
- Modify: `services/hostel-service/hostel/services.py`
- Create: `services/hostel-service/hostel/tests/test_direct_allocation.py`

**Interfaces:**
- Consumes: `Allocation.due_date` (Task 1), `allocation_one_active_per_student` constraint (Task 1).
- Produces: `create_allocation(room_id, student_user_code, tenant_id, fee_structure_id=None, university_name="", due_date=None)` — new `due_date` kwarg. When `fee_structure_id` is falsy, the allocation is created directly as `Allocation.Status.CONFIRMED` and `hostel.allocation.requested` is NOT published. When `fee_structure_id` is truthy, behavior is unchanged from today except `due_date` is now also included in the event payload and stamped onto the `Allocation` row. New `StudentAlreadyAllocatedError` exception (raised when the `IntegrityError` from the one-seat constraint fires) — Task 3's callers catch it exactly like they already catch `RoomFullError`.

- [ ] **Step 1: Write the failing tests**

Create `services/hostel-service/hostel/tests/test_direct_allocation.py`:

```python
"""create_allocation() with no fee_structure_id: confirms synchronously,
no hostel.allocation.requested event published, finance-service never
involved. With fee_structure_id: unchanged saga behavior, but due_date is
now stamped onto the Allocation and included in the event payload.
"""

import uuid

import pytest
from hostel.models import Allocation
from hostel.services import StudentAlreadyAllocatedError, create_allocation
from suerp_common.outbox import OutboxEvent

pytestmark = pytest.mark.django_db

from hostel.tests.test_allocate import _make_room  # noqa: E402


def test_no_fee_confirms_immediately_no_event():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")

    allocation = create_allocation(room.id, "STU001", tenant_id)

    assert allocation.status == Allocation.Status.CONFIRMED
    assert allocation.due_date is None
    assert not OutboxEvent.objects.filter(
        tenant_id=tenant_id, type="hostel.allocation.requested"
    ).exists()

    room.refresh_from_db()
    assert room.occupied_count == 1


def test_fee_with_due_date_stays_pending_and_publishes_event():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    fee_structure_id = uuid.uuid4()
    due_date = "2026-08-01"

    allocation = create_allocation(
        room.id,
        "STU001",
        tenant_id,
        fee_structure_id=fee_structure_id,
        due_date=due_date,
    )

    assert allocation.status == Allocation.Status.PENDING
    assert str(allocation.due_date) == due_date

    event = OutboxEvent.objects.get(tenant_id=tenant_id, type="hostel.allocation.requested")
    assert event.payload["fee_structure_id"] == str(fee_structure_id)
    assert event.payload["due_date"] == due_date


def test_second_allocation_for_same_student_raises():
    tenant_id = uuid.uuid4()
    room_a = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    room_b = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="102")
    create_allocation(room_a.id, "STU001", tenant_id)

    with pytest.raises(StudentAlreadyAllocatedError):
        create_allocation(room_b.id, "STU001", tenant_id)

    # Room b's seat must NOT have been consumed by the failed attempt.
    room_b.refresh_from_db()
    assert room_b.occupied_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_direct_allocation.py -v`
Expected: `test_no_fee_confirms_immediately_no_event` FAILS (`allocation.status == "pending"`, an event WAS published — current behavior always publishes and always stays pending); `test_fee_with_due_date_stays_pending_and_publishes_event` FAILS (`due_date` not in payload, `allocation.due_date` doesn't exist as a settable kwarg — well, the field exists from Task 1, but nothing stamps it yet); `test_second_allocation_for_same_student_raises` FAILS with `ImportError: cannot import name 'StudentAlreadyAllocatedError'`.

- [ ] **Step 3: Rewrite `create_allocation`**

Replace the full contents of `services/hostel-service/hostel/services.py`:

```python
"""Allocation creation, shared by the single-create and bulk-import
endpoints (hostel/views.py: AllocateView, AllocateBulkView) and by
room-request approval (hostel/views.py: ApproveRoomRequestView).

Extracted from AllocateView (Task 4.8) unchanged, so every caller reuses the
exact same lock/capacity-check/atomic-commit/outbox logic per allocation
instead of duplicating it. ``select_for_update()`` on the Room row prevents
concurrent over-allocation: two simultaneous calls against the same
last-open bed serialize on the row lock, so the second one observes the
incremented ``occupied_count`` and correctly raises ``RoomFullError``
instead of double-booking. State change and the ``hostel.allocation.
requested`` outbox event commit or roll back together (transactional-
outbox guarantee) — nothing here talks to RabbitMQ directly,
``drain_outbox_task`` relays it later.

``fee_structure_id`` is optional. When omitted (falsy), this is a DIRECT
allocation: no fee, no invoice, no payment saga — the Allocation is created
already CONFIRMED and no event is published at all. ``hostel.allocation.
requested`` is consumed ONLY by finance-service, purely to trigger invoice
creation (verified: no other service subscribes to it), so there is
nothing for finance-service to do when there's no fee — publishing the
event and waiting for a saga that will never happen would just be a
pointless round trip through the event bus for something this function
already knows synchronously.

When ``fee_structure_id`` IS given, ``due_date`` is required alongside it
(enforced by callers — see hostel/views.py — not here, since the
both-or-neither validation differs slightly per call site's serializer).
``due_date`` is stamped onto the Allocation and flows into the event
payload so finance-service's consumer can stamp the same deadline onto its
Invoice. ``hostel.tasks.release_stale_pending_allocations`` uses
``Allocation.due_date`` (not finance-service's copy) to release an unpaid
allocation once its deadline passes.
"""

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from hostel.models import Allocation, Room
from suerp_common.outbox import publish_event


class RoomFullError(Exception):
    """Raised when the target room has no free capacity."""


class StudentAlreadyAllocatedError(Exception):
    """Raised when student_user_code already holds a pending/confirmed
    allocation (allocation_one_active_per_student constraint)."""


def create_allocation(
    room_id,
    student_user_code,
    tenant_id,
    fee_structure_id=None,
    university_name="",
    due_date=None,
) -> Allocation:
    """Reserve a room seat and create an Allocation for student_user_code.

    Raises ``django.http.Http404`` if room_id doesn't resolve to a room in
    this tenant, ``RoomFullError`` if the room has no free capacity,
    ``StudentAlreadyAllocatedError`` if the student already holds an active
    (pending/confirmed) allocation anywhere.
    """
    try:
        with transaction.atomic():
            room = get_object_or_404(Room.objects.select_for_update(), id=room_id)

            if not room.is_available:
                raise RoomFullError(f"Room {room_id} is at full capacity.")

            initial_status = (
                Allocation.Status.PENDING if fee_structure_id else Allocation.Status.CONFIRMED
            )
            allocation = Allocation.objects.create(
                tenant_id=tenant_id,
                room=room,
                student_user_code=student_user_code,
                status=initial_status,
                due_date=due_date if fee_structure_id else None,
            )

            room.occupied_count += 1
            room.save(update_fields=["occupied_count"])

            if fee_structure_id:
                publish_event(
                    "hostel.allocation.requested",
                    tenant_id=tenant_id,
                    payload={
                        "allocation_id": str(allocation.id),
                        "student_user_code": allocation.student_user_code,
                        "room_id": str(room.id),
                        "fee_structure_id": str(fee_structure_id),
                        "university_name": university_name,
                        "due_date": str(due_date),
                    },
                )

            return allocation
    except IntegrityError as exc:
        raise StudentAlreadyAllocatedError(
            f"{student_user_code} already holds an active allocation."
        ) from exc
```

- [ ] **Step 4: Rebuild and restart hostel-service, run tests to verify they pass**

Run:
```bash
docker compose -f infra/docker-compose.yml build hostel-service
docker compose -f infra/docker-compose.yml up -d hostel-service
docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_direct_allocation.py -v
```
Expected: all 3 tests PASS.

- [ ] **Step 5: Run the full hostel-service suite to confirm no regressions**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest -q`
Expected: some existing tests will now FAIL — specifically any test in `test_allocate.py`/`test_saga.py`/`test_room_request_approval.py` that calls `create_allocation` or hits `AllocateView`/`ApproveRoomRequestView` WITHOUT a `fee_structure_id` and asserts `status == "pending"` (that assumption is no longer true — a no-fee allocation is now `confirmed` immediately). This is expected at this point in the plan; Task 3 updates `AllocateView`/`AllocateBulkView`/`ApproveRoomRequestView` to actually pass `fee_structure_id`/`due_date` through, and Task 3's own step also fixes any now-broken existing tests in `test_allocate.py` and `test_saga.py` that relied on the old always-pending, always-fee-charged behavior. Do NOT attempt to fix those tests in this task — note which ones fail and move to Task 3.

- [ ] **Step 6: Commit**

```bash
git add services/hostel-service/hostel/services.py services/hostel-service/hostel/tests/test_direct_allocation.py
git commit -m "feat(hostel-service): create_allocation confirms synchronously when no fee is given"
```

---

## Task 3: Wire `fee_structure_id`/`due_date` through `AllocateView`, `AllocateBulkView`, `ApproveRoomRequestView`

**Files:**
- Modify: `services/hostel-service/hostel/serializers.py` (`AllocateRequestSerializer`, `RoomRequestApproveSerializer`)
- Modify: `services/hostel-service/hostel/views.py` (`AllocateView`, `_parse_rows`, `AllocateBulkView`, `AvailableRoomsTemplateView`, `ApproveRoomRequestView`)
- Modify: `services/hostel-service/hostel/tests/test_allocate.py` (fix now-broken assumptions from Task 2)
- Modify: `services/hostel-service/hostel/tests/test_room_request_approval.py` (fix now-broken assumptions)
- Modify: `services/hostel-service/hostel/tests/test_allocate_bulk.py` (extend `_csv_file`/`_xlsx_file`/`_upload` helpers for the new columns, fix now-broken assumptions)
- Modify: `services/hostel-service/hostel/tests/test_available_template.py` (template now has 5 columns, not 3)
- Create: `services/hostel-service/hostel/tests/test_allocate_with_fee.py`

**Interfaces:**
- Consumes: `create_allocation(..., fee_structure_id=None, university_name="", due_date=None)` (Task 2), `StudentAlreadyAllocatedError`/`RoomFullError` (Task 2).
- Produces: `AllocateRequestSerializer` with two new optional fields; `_parse_rows` returning 4-tuples `(room_id, student_user_code, fee_structure_id_raw, due_date_raw)`; `AvailableRoomsTemplateView` CSV with 5 columns `room_id,room_name,student_user_code,fee_structure_id,due_date`.

- [ ] **Step 1: Update `AllocateRequestSerializer` and `RoomRequestApproveSerializer`**

In `services/hostel-service/hostel/serializers.py`, replace:

```python
class AllocateRequestSerializer(serializers.Serializer):
    room_id = serializers.UUIDField()
    student_user_code = serializers.RegexField(r"^[A-Za-z0-9_-]{1,30}$")
```

with:

```python
class AllocateRequestSerializer(serializers.Serializer):
    room_id = serializers.UUIDField()
    student_user_code = serializers.RegexField(r"^[A-Za-z0-9_-]{1,30}$")
    fee_structure_id = serializers.UUIDField(required=False)
    due_date = serializers.DateField(required=False)
```

and replace:

```python
class RoomRequestApproveSerializer(serializers.Serializer):
    fee_structure_id = serializers.UUIDField()
```

with:

```python
class RoomRequestApproveSerializer(serializers.Serializer):
    fee_structure_id = serializers.UUIDField(required=False)
    due_date = serializers.DateField(required=False)
```

- [ ] **Step 2: Write the failing tests for single-add and approval both-or-neither validation**

Create `services/hostel-service/hostel/tests/test_allocate_with_fee.py`:

```python
"""AllocateView / ApproveRoomRequestView: fee_structure_id and due_date are
optional but must be given together (both or neither). Neither given ->
direct allocation, confirmed immediately.
"""

import uuid
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db

from hostel.models import Allocation, RoomRequest  # noqa: E402
from hostel.tests.test_allocate import _auth_client, _make_room  # noqa: E402


@patch("hostel.views.resolve_user_by_code")
def test_allocate_with_no_fee_confirms_immediately(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    mock_resolve.return_value = {"user_code": "STU001"}
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {"room_id": str(room.id), "student_user_code": "STU001"},
        format="json",
    )

    assert response.status_code == 201, response.content
    assert response.json()["data"]["status"] == "confirmed"


@patch("hostel.views.resolve_user_by_code")
def test_allocate_with_fee_requires_due_date(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    mock_resolve.return_value = {"user_code": "STU001"}
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {
            "room_id": str(room.id),
            "student_user_code": "STU001",
            "fee_structure_id": str(uuid.uuid4()),
        },
        format="json",
    )

    assert response.status_code == 400
    assert Allocation.all_objects.filter(tenant_id=tenant_id).count() == 0


@patch("hostel.views.resolve_user_by_code")
def test_allocate_with_fee_and_due_date_stays_pending(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    mock_resolve.return_value = {"user_code": "STU001"}
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {
            "room_id": str(room.id),
            "student_user_code": "STU001",
            "fee_structure_id": str(uuid.uuid4()),
            "due_date": "2026-08-01",
        },
        format="json",
    )

    assert response.status_code == 201, response.content
    assert response.json()["data"]["status"] == "pending"


@patch("hostel.views.requests.get")
def test_approve_with_no_fee_confirms_immediately(mock_get):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    student_id = f"STU-{uuid.uuid4().hex[:8]}"
    student_client = _auth_client(tenant_id, role="student", user_id=student_id)
    create_response = student_client.post(
        "/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json"
    )
    request_id = create_response.json()["data"]["id"]

    mock_get.return_value.status_code = 200
    mock_get.return_value.ok = True
    mock_get.return_value.json.return_value = {
        "success": True,
        "data": {"id": str(tenant_id), "slug": "test-uni", "name": "Test University"},
    }

    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.post(
        f"/api/v1/hostel/room-requests/{request_id}/approve", {}, format="json"
    )

    assert response.status_code == 200, response.content
    assert response.json()["data"]["status"] == "approved"
    allocation = Allocation.all_objects.get(student_user_code=student_id, tenant_id=tenant_id)
    assert allocation.status == "confirmed"


@patch("hostel.views.requests.get")
def test_approve_with_fee_requires_due_date(mock_get):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    student_id = f"STU-{uuid.uuid4().hex[:8]}"
    student_client = _auth_client(tenant_id, role="student", user_id=student_id)
    create_response = student_client.post(
        "/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json"
    )
    request_id = create_response.json()["data"]["id"]

    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.post(
        f"/api/v1/hostel/room-requests/{request_id}/approve",
        {"fee_structure_id": str(uuid.uuid4())},
        format="json",
    )

    assert response.status_code == 400
    request = RoomRequest.all_objects.get(id=request_id)
    assert request.status == "pending"  # not flipped to approved
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_allocate_with_fee.py -v`
Expected: `test_allocate_with_fee_requires_due_date` and `test_approve_with_fee_requires_due_date` FAIL (no both-or-neither validation exists yet — a lone `fee_structure_id` is currently accepted). The other three should already pass once Step 1's serializer changes are in place, since `AllocateView`/`ApproveRoomRequestView` don't reject unknown-but-optional fields — but they won't actually route `fee_structure_id`/`due_date` into `create_allocation` yet, so re-check after Step 4.

- [ ] **Step 4: Update `AllocateView.post`**

In `services/hostel-service/hostel/views.py`, replace the body of `AllocateView.post`:

```python
    def post(self, request):
        serializer = AllocateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid allocation request.", errors=serializer.errors, status=400)

        room_id = serializer.validated_data["room_id"]
        student_user_code = serializer.validated_data["student_user_code"]
        fee_structure_id = serializer.validated_data.get("fee_structure_id")
        due_date = serializer.validated_data.get("due_date")

        if bool(fee_structure_id) != bool(due_date):
            return fail(
                "fee_structure_id and due_date must be given together, or neither.",
                status=400,
            )

        try:
            student = resolve_user_by_code(
                student_user_code, request.META.get("HTTP_AUTHORIZATION")
            )
        except LookupFailed as exc:
            return fail(str(exc), status=400 if exc.reason == "not_found" else 502)

        try:
            allocation = create_allocation(
                room_id,
                student["user_code"],
                get_current_tenant(),
                fee_structure_id=fee_structure_id,
                due_date=due_date,
            )
        except RoomFullError:
            return fail("Room at full capacity.", status=400)
        except StudentAlreadyAllocatedError as exc:
            return fail(str(exc), status=400)

        return ok(
            AllocationSerializer(allocation).data,
            message="Allocation created.",
            status=201,
        )
```

Add `StudentAlreadyAllocatedError` to the existing `from hostel.services import RoomFullError, create_allocation` import line, making it `from hostel.services import RoomFullError, StudentAlreadyAllocatedError, create_allocation`.

- [ ] **Step 5: Update `ApproveRoomRequestView.post`**

In `services/hostel-service/hostel/views.py`, modify `ApproveRoomRequestView.post`: add the both-or-neither check right after the existing `serializer.is_valid()` check, and pass `due_date` through to `create_allocation`:

```python
    def post(self, request, pk):
        serializer = RoomRequestApproveSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid approval payload.", errors=serializer.errors, status=400)

        fee_structure_id = serializer.validated_data.get("fee_structure_id")
        due_date = serializer.validated_data.get("due_date")
        if bool(fee_structure_id) != bool(due_date):
            return fail(
                "fee_structure_id and due_date must be given together, or neither.",
                status=400,
            )

        # Fetch by id alone (any status): an unknown id 404s, but an
        # already-decided one must reach the conditional update below so it
        # short-circuits to a clean 400 "already decided" — not a 404.
        room_request = get_object_or_404(RoomRequest.objects.all(), id=pk)

        # Flip pending -> approved FIRST, with an atomic conditional update that
        # only one caller can win (rowcount == 1). A duplicate/replayed approve
        # (or a concurrent one) sees the row already non-pending, so its update
        # affects 0 rows and we short-circuit BEFORE calling create_allocation —
        # this is what prevents a second Allocation + second invoice for the
        # same request. create_allocation only runs if we won the flip.
        university_name = resolve_institution_name(request.META.get("HTTP_AUTHORIZATION"))

        try:
            with transaction.atomic():
                flipped = RoomRequest.objects.filter(
                    id=pk, status=RoomRequest.Status.PENDING
                ).update(
                    status=RoomRequest.Status.APPROVED,
                    decided_on=timezone.now(),
                    decided_by=request.user.id,
                )
                if flipped != 1:
                    return fail("Room request has already been decided.", status=400)

                create_allocation(
                    room_request.room_id,
                    room_request.student_user_code,
                    get_current_tenant(),
                    fee_structure_id=fee_structure_id,
                    university_name=university_name,
                    due_date=due_date,
                )
        except RoomFullError:
            # The flip is rolled back with the surrounding atomic block, so the
            # request stays pending (not stranded as approved-with-no-allocation).
            return fail("Room is no longer available.", status=400)
        except StudentAlreadyAllocatedError as exc:
            return fail(str(exc), status=400)

        room_request.refresh_from_db()
        return ok(RoomRequestSerializer(room_request).data, message="Room request approved.")
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_allocate_with_fee.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 7: Fix now-broken existing tests in `test_allocate.py`, `test_saga.py`, `test_room_request_approval.py`**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_allocate.py hostel/tests/test_saga.py hostel/tests/test_room_request_approval.py -v` and read the failures. Every allocate/approve call in these files that asserts `status == "pending"` or expects a `hostel.allocation.requested` `OutboxEvent` to exist, but does NOT pass `fee_structure_id`, needs a `fee_structure_id`/`due_date` pair added to that specific request so its assumption (pending, event published) stays true — that IS the saga-path behavior this test is meant to exercise. For example, in `test_allocate.py`, `test_allocating_available_room_creates_pending_allocation_and_emits_event` should become:

```python
@patch("hostel.views.resolve_user_by_code")
def test_allocating_available_room_creates_pending_allocation_and_emits_event(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    mock_resolve.return_value = {"user_code": "STU001"}
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {
            "room_id": str(room.id),
            "student_user_code": "STU001",
            "fee_structure_id": str(uuid.uuid4()),
            "due_date": "2026-08-01",
        },
        format="json",
    )

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["status"] == "pending"

    event = OutboxEvent.objects.get(tenant_id=tenant_id, type="hostel.allocation.requested")
    assert event.payload["room_id"] == str(room.id)
```

Apply the same pattern (add `fee_structure_id`+`due_date` to the request/`create_allocation` call wherever a test needs the saga/pending path) across all three files. Any test that's specifically about the "room full" or "student already resolved" error paths and doesn't care about pending vs. confirmed can stay as-is, since `RoomFullError`/`LookupFailed` fire before the confirm/pending branch either way.

- [ ] **Step 8: Update `_parse_rows` and `AllocateBulkView` for the two new CSV columns**

In `services/hostel-service/hostel/views.py`, replace `_parse_rows`:

```python
def _parse_rows(upload, extension) -> list[tuple[str, str, str, str]]:
    """Parse an uploaded CSV/XLSX into a list of
    (room_id, student_user_code, fee_structure_id_raw, due_date_raw) tuples.

    Expects a header row with columns room_id, student_user_code,
    fee_structure_id, due_date (any order, case-insensitive).
    fee_structure_id/due_date may be blank per row.
    """
    columns = ("room_id", "student_user_code", "fee_structure_id", "due_date")

    if extension == "csv":
        text = upload.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
        if "room_id" not in fieldnames or "student_user_code" not in fieldnames:
            raise ValueError("CSV must have room_id and student_user_code columns.")
        rows = []
        for record in reader:
            normalized = {k.strip().lower(): v for k, v in record.items() if k}
            rows.append(tuple((normalized.get(col) or "").strip() for col in columns))
        return rows

    workbook = openpyxl.load_workbook(upload, read_only=True, data_only=True)
    sheet = workbook.active
    sheet_rows = list(sheet.iter_rows(values_only=True))
    if not sheet_rows:
        raise ValueError("XLSX file is empty.")
    header = [str(c).strip().lower() if c is not None else "" for c in sheet_rows[0]]
    if "room_id" not in header or "student_user_code" not in header:
        raise ValueError("XLSX must have room_id and student_user_code columns.")
    col_idx = {col: header.index(col) if col in header else None for col in columns}
    rows = []
    for record in sheet_rows[1:]:
        if record is None or all(c is None for c in record):
            continue

        def _cell(col):
            idx = col_idx[col]
            if idx is None or idx >= len(record):
                return ""
            value = record[idx]
            return str(value).strip() if value is not None else ""

        rows.append(tuple(_cell(col) for col in columns))
    return rows
```

Then update `AllocateBulkView.post`'s row loop. Find the current loop (`for row_number, (room_id_raw, student_user_code_raw) in enumerate(rows, start=1):`) and replace it and the body up through `AllocationImportRow.objects.create(...)`:

```python
        for row_number, (
            room_id_raw,
            student_user_code_raw,
            fee_structure_id_raw,
            due_date_raw,
        ) in enumerate(rows, start=1):
            error_message = ""
            allocation = None
            row_status = AllocationImportRow.Status.FAILED

            if not room_id_raw or not student_user_code_raw:
                error_message = "Row skipped: no user_code provided."
                row_status = AllocationImportRow.Status.SKIPPED
                skipped_count += 1
            elif bool(fee_structure_id_raw) != bool(due_date_raw):
                error_message = "fee_structure_id and due_date must be given together, or neither."
                fail_count += 1
            else:
                try:
                    if student_user_code_raw not in code_cache:
                        code_cache[student_user_code_raw] = resolve_user_by_code(
                            student_user_code_raw, auth_header
                        )
                    student = code_cache[student_user_code_raw]

                    room_uuid = uuid_lib.UUID(room_id_raw)
                    fee_structure_id = (
                        uuid_lib.UUID(fee_structure_id_raw) if fee_structure_id_raw else None
                    )
                    allocation = create_allocation(
                        room_uuid,
                        student["user_code"],
                        tenant_id,
                        fee_structure_id=fee_structure_id,
                        due_date=due_date_raw or None,
                    )
                    row_status = AllocationImportRow.Status.SUCCESS
                    success_count += 1
                except LookupFailed as exc:
                    error_message = str(exc)
                    fail_count += 1
                except Http404:
                    error_message = f"Room {room_id_raw} not found."
                    fail_count += 1
                except RoomFullError as exc:
                    error_message = str(exc)
                    fail_count += 1
                except StudentAlreadyAllocatedError as exc:
                    error_message = str(exc)
                    fail_count += 1
                except ValueError as exc:
                    error_message = str(exc)
                    fail_count += 1

            AllocationImportRow.objects.create(
                tenant_id=tenant_id,
                batch=batch,
                row_number=row_number,
                room_id_raw=room_id_raw,
                student_user_code_raw=student_user_code_raw,
                status=row_status,
                error_message=error_message,
                allocation=allocation,
            )
```

(The `batch.success_count = ...` block and the final `return ok(...)` below stay unchanged.)

- [ ] **Step 9: Update `AvailableRoomsTemplateView` to include the two new columns**

In `services/hostel-service/hostel/views.py`, update the `get` method:

```python
    def get(self, request):
        from django.http import HttpResponse

        rooms = (
            Room.objects.filter(occupied_count__lt=F("capacity"))
            .select_related("block")
            .order_by("block__name", "room_no")
        )

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            ["room_id", "room_name", "student_user_code", "fee_structure_id", "due_date"]
        )
        for room in rooms:
            free_seats = room.capacity - room.occupied_count
            room_name = f"{room.block.name} - {room.room_no}"
            for _ in range(free_seats):
                writer.writerow([str(room.id), room_name, "", "", ""])

        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="allocation-template.csv"'
        return response
```

- [ ] **Step 10: Update `test_available_template.py` for the 5-column header**

In `services/hostel-service/hostel/tests/test_available_template.py`, update both tests' `reader.fieldnames` assertions from `["room_id", "room_name", "student_user_code"]` to `["room_id", "room_name", "student_user_code", "fee_structure_id", "due_date"]`, and in `test_returns_one_row_per_free_seat`, add assertions that `row["fee_structure_id"] == ""` and `row["due_date"] == ""` for each row.

- [ ] **Step 11: Update `test_allocate_bulk.py` helpers and existing tests**

In `services/hostel-service/hostel/tests/test_allocate_bulk.py`, update `_csv_file`/`_xlsx_file` to accept the two new optional columns (default blank), matching the 4-tuple shape:

```python
def _csv_file(rows, filename="import.csv"):
    """rows: list of (room_id, student_user_code) 2-tuples OR
    (room_id, student_user_code, fee_structure_id, due_date) 4-tuples."""
    lines = ["room_id,student_user_code,fee_structure_id,due_date"]
    for r in rows:
        if len(r) == 2:
            r = (r[0], r[1], "", "")
        lines.append(",".join(r))
    content = "\n".join(lines).encode("utf-8")
    return io.BytesIO(content), filename


def _xlsx_file(rows, filename="import.xlsx"):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["room_id", "student_user_code", "fee_structure_id", "due_date"])
    for r in rows:
        if len(r) == 2:
            r = (r[0], r[1], "", "")
        sheet.append(list(r))
    buf = io.BytesIO()
    workbook.save(buf)
    buf.seek(0)
    return buf, filename
```

Then run the file's existing tests, check which ones assert `allocation.status == "pending"` for a plain 2-tuple row with no fee — those need updating to expect `"confirmed"` now, OR (preferred, to keep exercising the saga path where that was the test's actual intent) extend that row's tuple to include a `fee_structure_id`/`due_date` pair. Read each failure and choose per-test based on what the test is actually verifying (bulk-row success/fail counting doesn't care about pending-vs-confirmed; anything asserting on `Allocation.status` or `OutboxEvent` does).

- [ ] **Step 12: Run the full hostel-service suite**

Run: `docker compose -f infra/docker-compose.yml build hostel-service && docker compose -f infra/docker-compose.yml up -d hostel-service && docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest -q`
Expected: all tests pass, 0 failures.

- [ ] **Step 13: Commit**

```bash
git add services/hostel-service/hostel/serializers.py services/hostel-service/hostel/views.py services/hostel-service/hostel/tests/
git commit -m "feat(hostel-service): optional fee_structure_id+due_date on single-add, bulk-CSV, and room-request approval"
```

---

## Task 4: `release_stale_pending_allocations` uses `due_date` instead of fixed 30-minute timeout

**Files:**
- Modify: `services/hostel-service/hostel/tasks.py`
- Modify: `services/hostel-service/hostel/tests/test_saga.py` (timeout-related tests)

**Interfaces:**
- Consumes: `Allocation.due_date` (Task 1).
- Produces: no signature change to `release_stale_pending_allocations()` (still a zero-arg Celery task returning an int count).

- [ ] **Step 1: Read the existing timeout tests to understand what must change**

Read `services/hostel-service/hostel/tests/test_saga.py`, locate every test whose name contains `timeout` (per the Global Constraints note, these exist: `test_timeout_guard_does_not_release_paid_allocation`, `test_release_stale_pending_allocations_releases_timed_out_ones_only`, `test_timeout_does_not_release_uninvoiced_stale_allocation`, `test_timeout_never_releases_paid_but_uncorrelated_allocation`). Each currently manipulates `Allocation.allocated_on` (backdating it past `PENDING_TIMEOUT`) to simulate staleness — these must change to set `Allocation.due_date` to a past date instead.

- [ ] **Step 2: Update the timeout tests**

For each of the four tests identified in Step 1, replace whatever backdates `allocated_on` (e.g. `allocation.allocated_on = timezone.now() - timedelta(minutes=31)`) with setting `due_date` directly:

```python
allocation.due_date = (timezone.now() - timedelta(days=1)).date()
allocation.save(update_fields=["due_date"])
```

And for the "not yet due" counterpart test (`..._releases_timed_out_ones_only`'s non-stale allocation), set:

```python
allocation.due_date = (timezone.now() + timedelta(days=7)).date()
allocation.save(update_fields=["due_date"])
```

For `test_timeout_does_not_release_uninvoiced_stale_allocation`: this test's point is that an allocation with no `invoice_id` yet is never a timeout candidate regardless of staleness — keep that structure, just set a past `due_date` on it too (to prove the `invoice_id__isnull=False` filter is what's actually protecting it, not merely the absence of a due date).

- [ ] **Step 3: Run the timeout tests to verify they fail against current code**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_saga.py -k timeout -v`
Expected: FAIL — `release_stale_pending_allocations` still checks `allocated_on` against the fixed `PENDING_TIMEOUT`, not `due_date`, so backdating `due_date` alone doesn't trigger release yet.

- [ ] **Step 4: Rewrite `release_stale_pending_allocations`**

In `services/hostel-service/hostel/tasks.py`, replace the module docstring's timeout paragraph and the function:

```python
"""Celery tasks for hostel.

``drain_outbox_task`` is wired to Celery Beat (see ``config.settings.
CELERY_BEAT_SCHEDULE``) to periodically relay unpublished ``OutboxEvent`` rows
to RabbitMQ. Mirrors billing/tasks.py in finance-service: one thin task
delegating to ``suerp_common.outbox.drain_outbox``.

``release_stale_pending_allocations`` is the saga's EXPIRY compensating
action: an Allocation created with a fee (Task 4.8/hostel/services.py:
create_allocation) is ``pending`` with a mandatory ``due_date`` until
finance-service settles the invoice (see ``hostel.consumers``). If the
student never pays by that date, this task releases the allocation and
frees the room seat, same as ``handle_payment_failed`` would. It runs
outside any request, so it uses ``Allocation.all_objects``/
``Room.all_objects`` (no ambient tenant) and handles each allocation in its
own transaction so one bad row (e.g. its room was deleted) can't block the
rest of the batch.

A no-fee (direct) allocation is confirmed synchronously at creation and
never reaches this queryset — nothing to expire.
"""

import logging

from django.db import transaction
from django.utils import timezone
from hostel.models import Allocation, PaymentOutcome, Room
from suerp_common.outbox import drain_outbox

logger = logging.getLogger(__name__)


@shared_task(name="hostel.drain_outbox_task")
def drain_outbox_task() -> int:
    return drain_outbox()


@shared_task(name="hostel.release_stale_pending_allocations")
def release_stale_pending_allocations() -> int:
    """Release Allocations whose payment due_date has passed unpaid.

    Returns the number of allocations released. Each allocation is released
    in its own transaction so a failure on one row doesn't prevent the rest
    of the batch from being processed.
    """
    today = timezone.now().date()
    # Only invoiced allocations past their due_date are candidates. An
    # allocation with no invoice_id hasn't reached the payment stage of the
    # saga yet (or is a no-fee allocation, which has no due_date at all and
    # is already confirmed, never pending). This filter ALSO closes the
    # saga-timeout hole: in the out-of-order window a
    # finance.payment.success can be recorded as PaymentOutcome(applied=
    # False) BEFORE finance.invoice.created stamps the allocation, so a
    # PAID allocation still has invoice_id IS NULL. Excluding null-invoice
    # allocations here means such a paid-but-uncorrelated allocation is
    # never released regardless of event ordering — once invoice.created
    # lands it reconciles to CONFIRMED and is no longer pending.
    stale_ids = list(
        Allocation.all_objects.filter(
            status=Allocation.Status.PENDING,
            due_date__lt=today,
            invoice_id__isnull=False,
        ).values_list("id", flat=True)
    )

    released = 0
    for allocation_id in stale_ids:
        try:
            with transaction.atomic():
                allocation = Allocation.all_objects.select_for_update().get(id=allocation_id)
                if allocation.status != Allocation.Status.PENDING:
                    continue  # already handled (e.g. by a payment event) — skip
                if allocation.invoice_id is None:
                    continue  # not invoiced yet — not an expiry candidate
                # Never release an invoiced allocation that has a recorded
                # payment outcome (in particular a success): its terminal event
                # arrived and is either applied or awaiting correlation.
                if PaymentOutcome.all_objects.filter(
                    tenant_id=allocation.tenant_id,
                    invoice_id=allocation.invoice_id,
                ).exists():
                    continue
                room = Room.all_objects.select_for_update().get(pk=allocation.room_id)
                allocation.status = Allocation.Status.RELEASED
                allocation.save(update_fields=["status"])
                room.occupied_count = max(0, room.occupied_count - 1)
                room.save(update_fields=["occupied_count"])
                released += 1
        except Exception:
            logger.exception("Failed to release stale allocation id=%s", allocation_id)
    return released
```

Note: `from celery import shared_task` and `from datetime import timedelta` imports — `shared_task` stays (still used), `timedelta` is no longer used in this file and should be dropped from the imports if nothing else in the file needs it (check before removing).

- [ ] **Step 5: Run tests to verify they pass**

Run:
```bash
docker compose -f infra/docker-compose.yml build hostel-service
docker compose -f infra/docker-compose.yml up -d hostel-service
docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_saga.py -v
```
Expected: all tests in this file PASS.

- [ ] **Step 6: Run the full hostel-service suite**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest -q`
Expected: all tests pass, 0 failures.

- [ ] **Step 7: Commit**

```bash
git add services/hostel-service/hostel/tasks.py services/hostel-service/hostel/tests/test_saga.py
git commit -m "feat(hostel-service): release_stale_pending_allocations uses due_date instead of fixed 30-minute timeout"
```

---

## Task 5: finance-service — `Invoice.due_date`, delete `HOSTEL_FEE_AMOUNT` fallback

**Files:**
- Modify: `services/finance-service/billing/models.py` (`Invoice`)
- Modify: `services/finance-service/billing/consumers.py` (`handle_allocation_requested`, delete `HOSTEL_FEE_AMOUNT`/`_resolve_hostel_fee_amount`)
- Create: `services/finance-service/billing/migrations/0002_invoice_due_date.py` (generated)
- Modify: `services/finance-service/billing/tests/test_consumers.py` (has two fallback tests being deleted)
- Modify: `services/finance-service/billing/tests/test_consumer.py` (note: singular — a separate pre-existing file from `test_consumers.py` plural; has a third test relying on the same fallback default)

**Interfaces:**
- Consumes: `hostel.allocation.requested` event payload now always containing a real `fee_structure_id` and `due_date` (Task 3 guarantees finance-service never receives this event without both, since the no-fee path never publishes it at all).
- Produces: `Invoice.due_date` (nullable `DateField`, though in practice always populated by this consumer going forward).

- [ ] **Step 1: Read the existing fallback tests being deleted or fixed**

Read `services/finance-service/billing/tests/test_consumers.py:56-76` — two tests, `test_falls_back_to_hardcoded_default_without_fee_structure` and `test_missing_fee_structure_id_falls_back_gracefully`, both assert `invoice.amount == Decimal("5000.00")` when no valid `fee_structure_id` is given. Both test the exact fallback behavior being deleted in this task.

Also read `services/finance-service/billing/tests/test_consumer.py:33-69` (singular filename — a separate pre-existing test file) — `test_handling_allocation_requested_creates_pending_hostel_invoice_and_emits_event` builds its event via a local `_allocation_requested_event` helper that never sets `fee_structure_id` at all, then asserts the resulting `invoice.amount == Decimal("5000.00")` (the old fallback). This test needs its helper call updated to pass a real `fee_structure_id`, not deletion — it's exercising the legitimate "invoice created from event" path, just via the wrong (now-removed) amount-resolution route.

- [ ] **Step 2: Delete the fallback tests in `test_consumers.py`, write the replacement**

Delete `test_falls_back_to_hardcoded_default_without_fee_structure` and `test_missing_fee_structure_id_falls_back_gracefully` from `test_consumers.py` entirely. Add this test to the same file:

```python
def test_missing_fee_structure_id_resolves_to_deleted_fee_structure_raises():
    """A fee_structure_id that doesn't resolve (deleted/cross-tenant/typo'd)
    is now a hard failure, not a silent fallback to a hardcoded amount —
    the caller (hostel-service) already validated the id exists at
    allocation time via its own FeeStructure lookup... """
```

Confirmed by grep: hostel-service never validates `fee_structure_id` against a real `FeeStructure` anywhere (`grep -rn "FeeStructure" services/hostel-service/hostel/*.py` returns nothing but a docstring mention) — it's finance-service's model, cross-service, no live check happens at allocation time. So a stray/deleted/cross-tenant `fee_structure_id` CAN reach this consumer. Write this test:

```python
def test_unresolvable_fee_structure_id_logs_and_skips_invoice_creation():
    """A fee_structure_id that doesn't resolve (deleted/cross-tenant/typo'd)
    must not crash the consumer or silently create an invoice with a wrong
    amount — log and skip, matching handle_invoice_created's existing
    best-effort correlation-failure pattern.
    """
    tenant_id = uuid.uuid4()
    event = {
        "tenant_id": tenant_id,
        "payload": {
            "allocation_id": str(uuid.uuid4()),
            "student_user_code": "STU001",
            "room_id": str(uuid.uuid4()),
            "fee_structure_id": str(uuid.uuid4()),  # doesn't exist
            "due_date": "2026-08-01",
            "university_name": "Test University",
        },
    }

    handle_allocation_requested(event)  # must not raise

    assert not Invoice.all_objects.filter(tenant_id=tenant_id).exists()
```

- [ ] **Step 3: Fix `test_consumer.py`'s fallback-dependent test**

In `services/finance-service/billing/tests/test_consumer.py`, update `_allocation_requested_event` to accept and pass through `fee_structure_id`/`due_date`:

```python
def _allocation_requested_event(
    tenant_id, student_user_code=None, allocation_id=None, room_id=None,
    fee_structure_id=None, due_date=None,
):
    payload = {
        "allocation_id": str(allocation_id or uuid.uuid4()),
        "student_user_code": student_user_code or "STU-100",
        "room_id": str(room_id or uuid.uuid4()),
        "fee_structure_id": str(fee_structure_id) if fee_structure_id else None,
        "due_date": due_date,
    }
    return build_event("hostel.allocation.requested", tenant_id=str(tenant_id), payload=payload)
```

Then update `test_handling_allocation_requested_creates_pending_hostel_invoice_and_emits_event` to create a real `FeeStructure` first and pass its id/amount through, replacing the hardcoded `Decimal("5000.00")` assertions with assertions against that fee structure's actual amount:

```python
def test_handling_allocation_requested_creates_pending_hostel_invoice_and_emits_event():
    tenant_id = uuid.uuid4()
    student_user_code = "STU-100"
    allocation_id = uuid.uuid4()
    fee_structure = FeeStructure.all_objects.create(
        tenant_id=tenant_id, name="Hostel Fee", amount=Decimal("6000.00"), purpose="hostel"
    )
    event = _allocation_requested_event(
        tenant_id,
        student_user_code=student_user_code,
        allocation_id=allocation_id,
        fee_structure_id=fee_structure.id,
        due_date="2026-08-01",
    )

    handle_allocation_requested(event)

    invoices = Invoice.all_objects.filter(tenant_id=tenant_id, student_user_code=student_user_code)
    assert invoices.count() == 1
    invoice = invoices.first()
    assert invoice.amount == Decimal("6000.00")
    assert invoice.purpose == "hostel"
    assert invoice.status == Invoice.Status.PENDING
    assert str(invoice.due_date) == "2026-08-01"

    events = OutboxEvent.objects.filter(type="finance.invoice.created")
    assert events.count() == 1
    emitted = events.first()
    assert str(emitted.tenant_id) == str(tenant_id)
    assert emitted.payload["invoice_id"] == str(invoice.id)
    assert emitted.payload["student_user_code"] == student_user_code
    assert emitted.payload["allocation_id"] == str(allocation_id)
    assert emitted.payload["amount"] == "6000.00"
    assert emitted.payload["purpose"] == "hostel"
```

Check the file's other tests (`test_handling_same_event_twice_is_idempotent` and any others using `_allocation_requested_event`) — since the helper's signature grew new optional kwargs with sensible None defaults, calls that don't pass them still work, but if any other test also asserts `Decimal("5000.00")` without passing a `fee_structure_id`, apply the same fix (create a real `FeeStructure`, pass its id, assert against its actual amount).

- [ ] **Step 4: Update `Invoice` model**

In `services/finance-service/billing/models.py`, add a `due_date` field to `Invoice` (find the class and add alongside `amount`/`university_name`):

```python
    # Payment deadline, mirrored from hostel-service's Allocation.due_date at
    # invoice-creation time (see billing/consumers.py:
    # handle_allocation_requested) — each service keeps its own copy since
    # there's no cross-service FK (DB-per-service). Used by the student-
    # facing UI to show "due by <date>"; hostel-service's own copy (not this
    # one) is what release_stale_pending_allocations actually checks.
    due_date = models.DateField(null=True, blank=True)
```

- [ ] **Step 5: Rewrite `handle_allocation_requested` and delete the fallback**

In `services/finance-service/billing/consumers.py`, add a logger (this file has none yet, unlike hostel-service's `consumers.py` which already has one) — change:

```python
from decimal import Decimal

from billing.models import FeeStructure, Invoice
from django.db import transaction
from suerp_common.inbox import idempotent
from suerp_common.outbox import publish_event
```

to:

```python
import logging

from billing.models import FeeStructure, Invoice
from django.db import transaction
from suerp_common.inbox import idempotent
from suerp_common.outbox import publish_event

logger = logging.getLogger(__name__)
```

(`Decimal` is dropped since `HOSTEL_FEE_AMOUNT = Decimal("5000.00")` — the only user of that import — is deleted below; `fee_structure.amount` is already a `Decimal` from the model field, no explicit construction needed.)

Then delete `HOSTEL_FEE_AMOUNT` and `_resolve_hostel_fee_amount` entirely, and rewrite `handle_allocation_requested`:

```python
@idempotent
def handle_allocation_requested(event: dict) -> None:
    """Handle ``hostel.allocation.requested``: create a pending hostel Invoice.

    Expects ``event["payload"]`` to contain ``allocation_id``,
    ``student_user_code``, ``room_id``, ``fee_structure_id``, ``due_date``,
    and ``university_name``. hostel-service's create_allocation() only ever
    publishes this event when a fee was actually chosen — a direct/no-fee
    allocation confirms synchronously in hostel-service and never publishes
    this event at all, so every delivery here always carries a real
    fee_structure_id/due_date pair.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    student_user_code = payload["student_user_code"]
    allocation_id = payload["allocation_id"]
    fee_structure_id = payload["fee_structure_id"]
    due_date = payload.get("due_date")
    university_name = payload.get("university_name") or ""

    fee_structure = FeeStructure.all_objects.filter(tenant_id=tenant_id, id=fee_structure_id).first()
    if fee_structure is None:
        logger.warning(
            "hostel.allocation.requested for unresolvable fee_structure_id=%s tenant_id=%s "
            "allocation_id=%s — skipping invoice creation",
            fee_structure_id,
            tenant_id,
            allocation_id,
        )
        return
    amount = fee_structure.amount

    with transaction.atomic():
        invoice = Invoice.all_objects.create(
            tenant_id=tenant_id,
            student_user_code=student_user_code,
            amount=amount,
            purpose="hostel",
            status=Invoice.Status.PENDING,
            university_name=university_name,
            due_date=due_date,
        )

        publish_event(
            "finance.invoice.created",
            tenant_id=tenant_id,
            payload={
                "invoice_id": str(invoice.id),
                "student_user_code": student_user_code,
                "allocation_id": allocation_id,
                "amount": str(amount),
                "purpose": "hostel",
            },
        )
```

Also remove the now-unused `from decimal import Decimal` import if nothing else in the file needs it (check first).

- [ ] **Step 6: Generate the migration**

Run: `docker compose -f infra/docker-compose.yml exec finance-service python manage.py makemigrations billing`
Expected: creates `billing/migrations/0002_invoice_due_date.py` (or similarly auto-named) adding the `due_date` field.

- [ ] **Step 7: Rebuild and restart finance-service, run its tests**

Run:
```bash
docker compose -f infra/docker-compose.yml build finance-service
docker compose -f infra/docker-compose.yml up -d finance-service
docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/finance" finance-service pytest -q
```
Expected: all tests pass, including `test_unresolvable_fee_structure_id_logs_and_skips_invoice_creation` from Step 2.

- [ ] **Step 8: Commit**

```bash
git add services/finance-service/billing/models.py services/finance-service/billing/consumers.py services/finance-service/billing/migrations/ services/finance-service/billing/tests/
git commit -m "feat(finance-service): add Invoice.due_date, remove HOSTEL_FEE_AMOUNT hardcoded fallback"
```

---

## Task 6: Frontend — fee/due-date pickers on single-add, bulk-CSV, and room-request approval

**Files:**
- Modify: `frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx` (`CreateAllocation`, `RoomRequestQueue`, `BulkAllocationImport` help text)
- Modify: `frontend/su-erp-web/src/app/(dashboard)/admin/students/new/page.tsx` if it also creates allocations directly (check first — if it only creates student accounts via bulk auth-service upload and doesn't touch `/api/v1/hostel/allocate*` at all, skip this file entirely)

**Interfaces:**
- Consumes: `POST /api/v1/hostel/allocate` (now accepts optional `fee_structure_id`/`due_date`), `POST /api/v1/hostel/room-requests/{id}/approve` (same), `GET /api/v1/finance/fee-structures` (already used by `RoomRequestQueue` — reuse the same fetched list for `CreateAllocation`'s new picker).

- [ ] **Step 1: Check whether `admin/students/new/page.tsx` touches allocation endpoints**

Run: `grep -n "hostel/allocate\|fee_structure" "frontend/su-erp-web/src/app/(dashboard)/admin/students/new/page.tsx"`. If no matches, this file is unaffected — skip it for the rest of this task (it only creates student *accounts*, not room allocations).

- [ ] **Step 2: Read the current `CreateAllocation` component**

Read `frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx` in full to find `CreateAllocation`'s current props/state/submit handler (it currently posts `{room_id, student_user_code}` to `/api/v1/hostel/allocate`) and `RoomRequestQueue`'s existing `feeStructures`/`selectedFee` state (it already fetches `/api/v1/finance/fee-structures` and has a `<Select>` fee picker per pending request — the exact pattern to mirror).

- [ ] **Step 3: Add an optional fee+due-date picker to `CreateAllocation`**

Extend `CreateAllocation` to fetch `/api/v1/finance/fee-structures` (same call `RoomRequestQueue` already makes — either lift it to a shared parent-level fetch passed down as a prop, following whatever pattern minimizes duplicate fetching given the two components' actual parent/sibling relationship in this file, or fetch independently if they're not already siblings under a shared loader) and add two optional form fields: a fee-structure `<Select>` (with a "No fee (direct allocation)" empty option, matching `RoomRequestQueue`'s existing `<option value="">Select fee…</option>` pattern) and a `<Input type="date">` for due date, shown/required only when a fee is selected. On submit, include `fee_structure_id`/`due_date` in the POST body only if a fee was actually picked (omit both keys entirely when direct/no-fee, so the request body matches what `AllocateRequestSerializer` expects for the no-fee case).

- [ ] **Step 4: Add the same picker to `RoomRequestQueue`'s approve action**

`RoomRequestQueue` already has `selectedFee`/`feeStructures` and requires picking a fee before enabling Approve (per the existing "Pick a fee structure before approving" validation). Change this to make the fee picker genuinely optional: add a due-date `<Input type="date">` next to the existing fee `<Select>` per row, enable Approve when EITHER both fee+due-date are filled OR both are empty (mirror the both-or-neither rule), and update the `approve` function to omit `fee_structure_id`/`due_date` from the POST body entirely when neither was picked, rather than always sending `fee_structure_id`.

- [ ] **Step 5: Update `BulkAllocationImport`'s help text**

Find `BulkAllocationImport` in the same file and update any static help text describing the CSV columns (e.g. "Download available-rooms template" description) to mention the two new optional `fee_structure_id`/`due_date` columns, so a warden filling in the downloaded template understands they can leave them blank for a direct allocation or fill both for a fee-bearing one.

- [ ] **Step 6: Rebuild and restart the frontend container**

Run: `docker compose -f infra/docker-compose.yml build frontend && docker compose -f infra/docker-compose.yml up -d frontend`

- [ ] **Step 7: Manually verify in the browser**

Log in as warden (`suresh.verma@pdpmiiitdmj.ac.in` / `Passw0rd123`, institution slug `pdpmiiitdmj`):
- Create a direct allocation (no fee picked) for a student with no existing active allocation — confirm it shows status `confirmed` immediately in the allocations table, and confirm no invoice appears for that student in the admin/finance views.
- Create an allocation WITH a fee but no due date — confirm the UI blocks submission or the API returns a clear 400 (whichever the form validation does — should prevent the bad request client-side too, not just rely on the server 400).
- Create an allocation with both fee and due date — confirm it shows `pending` and an invoice appears.
- Approve a pending room request with no fee selected — confirm the resulting allocation is `confirmed` immediately.
- Try allocating a student who already holds an active allocation — confirm a clear error, not a 500.

- [ ] **Step 8: Commit**

```bash
git add -- "frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx"
git commit -m "feat(warden-ui): optional fee/due-date pickers for direct allocation, bulk upload, and room-request approval"
```

---

## Self-Review Notes

- **Spec coverage:** All 4 spec sections have tasks — §1 (no-fee synchronous confirm) = Task 2; §2 (mandatory due_date-with-fee across all 3 entry points) = Tasks 3, 6; §3 (due_date replaces 30-min timeout) = Task 4; §4 (one-seat-per-student) = Task 1. finance-service's `Invoice.due_date`/fallback removal = Task 5.
- **Type consistency:** `create_allocation`'s new `due_date` kwarg, `StudentAlreadyAllocatedError`, and the `_parse_rows` 4-tuple shape are defined once (Tasks 1/2/3) and referenced identically in every later task that touches them (Tasks 3, 4, 5, 6).
- **No placeholders:** every step has literal file paths, complete code, and exact commands with expected output. Verified by grep before writing Task 5 that hostel-service never validates `fee_structure_id` pre-flight, so the "unresolvable id" path in `handle_allocation_requested` is a real, reachable case (not hypothetical) — handled by logging and skipping invoice creation, matching this codebase's existing best-effort correlation-failure pattern (`handle_invoice_created`'s `Allocation.DoesNotExist` catch).
- **Sequencing:** Task 2 deliberately breaks some existing tests (documented in its own Step 5) that Task 3 then fixes — flagged explicitly in both tasks so an implementer isn't alarmed mid-task-2 by red tests that are expected to stay red until task 3.
