# Room Occupancy Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the bulk-upload CSV template to emit one row per free seat (not one per room), add an admin endpoint to edit room capacity, and add a warden endpoint to manually release an allocation.

**Architecture:** All three fixes live entirely in `services/hostel-service` (models/serializers/views/urls) plus two small frontend pages (`admin/page.tsx`, `warden/page.tsx`). No new models, no new events beyond reusing the existing `hostel.allocation.released` event shape for the new manual-release path. Each task is independently testable and independently deployable.

**Tech Stack:** Django 5 + DRF (hostel-service), Next.js/TypeScript (frontend), pytest + `rest_framework.test.APIClient` for backend tests.

## Global Constraints

- Every endpoint uses the existing envelope helpers `ok`/`fail` from `suerp_common.envelope` — never raw DRF `Response`.
- Every endpoint uses `role_required(...)` from `suerp_common.permissions` for permissions — never hand-rolled role checks.
- All DB writes that touch `Room.occupied_count` alongside an `Allocation.status` change happen inside one `transaction.atomic()` block with `select_for_update()` on the `Room` row (matches `hostel/consumers.py`'s existing pattern) — prevents lost updates under concurrent requests.
- Tenant scoping: views use the default `Room.objects`/`Allocation.objects` (auto-scoped `TenantManager`) since these run inside a real request with ambient tenant context — NOT `all_objects` (that's only for the standalone consumer process, per `hostel/consumers.py`'s own docstring).
- Existing hostel-service test suite (61 tests before this work) must keep passing throughout. Run via: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest -q` (pgbouncer can't create databases, so tests must bypass it and hit `suerp-postgres` directly).
- After backend changes: rebuild + restart the container for changes to take effect: `docker compose -f infra/docker-compose.yml build hostel-service && docker compose -f infra/docker-compose.yml up -d hostel-service`. Frontend: `docker compose -f infra/docker-compose.yml build frontend && docker compose -f infra/docker-compose.yml up -d frontend` (Next.js prod build in Docker does not hot-reload).

---

## Task 1: CSV template — one row per free seat

**Files:**
- Modify: `services/hostel-service/hostel/views.py:75-104` (`AvailableRoomsTemplateView`)
- Modify: `services/hostel-service/hostel/tests/test_available_template.py` (existing test needs updating; new test needs adding)

**Interfaces:**
- Consumes: `Room.objects.filter(occupied_count__lt=F("capacity"))` — the existing available-rooms queryset, unchanged filter.
- Produces: no new symbols — same view, same URL, same CSV column headers (`room_id,room_name,student_user_code`). Only the row-count-per-room behavior changes. Nothing downstream depends on the old one-row-per-room behavior (`AllocateBulkView` already handles duplicate `room_id` rows correctly — verified: it resolves and calls `create_allocation` per row independently, and `RoomFullError` is already handled per-row).

- [ ] **Step 1: Update the existing test to expect 2 rows for a capacity-2, occupied-0 room**

Open `services/hostel-service/hostel/tests/test_available_template.py`. Replace `test_returns_only_available_rooms_as_csv` with:

```python
def test_returns_one_row_per_free_seat():
    tenant_id = uuid.uuid4()
    available = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    partially_full = _make_room(tenant_id, capacity=3, occupied_count=2, room_no="103")
    full = _make_room(tenant_id, capacity=1, occupied_count=1, room_no="102")
    client = _auth_client(tenant_id, role="warden")

    response = client.get("/api/v1/hostel/rooms/available-template")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]

    content = response.content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    assert reader.fieldnames == ["room_id", "room_name", "student_user_code"]
    rows = list(reader)

    available_rows = [r for r in rows if r["room_id"] == str(available.id)]
    assert len(available_rows) == 2
    for row in available_rows:
        assert row["room_name"] == f"{available.block.name} - {available.room_no}"
        assert row["student_user_code"] == ""

    partial_rows = [r for r in rows if r["room_id"] == str(partially_full.id)]
    assert len(partial_rows) == 1

    assert str(full.id) not in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_available_template.py -v`
Expected: `test_returns_one_row_per_free_seat` FAILS — `len(available_rows) == 2` assertion fails because the current view only writes 1 row per room.

- [ ] **Step 3: Fix `AvailableRoomsTemplateView.get` to write one row per free seat**

In `services/hostel-service/hostel/views.py`, replace the `get` method body of `AvailableRoomsTemplateView` (currently lines 87-104):

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
        writer.writerow(["room_id", "room_name", "student_user_code"])
        for room in rooms:
            free_seats = room.capacity - room.occupied_count
            room_name = f"{room.block.name} - {room.room_no}"
            for _ in range(free_seats):
                writer.writerow([str(room.id), room_name, ""])

        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="allocation-template.csv"'
        return response
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_available_template.py -v`
Expected: both tests PASS (`test_returns_one_row_per_free_seat`, `test_ordered_by_block_then_room_no` — the ordering test is unaffected since it uses capacity=2/occupied=0 rooms consistently, producing 2 rows each in the same relative order).

- [ ] **Step 5: Run the full hostel-service suite to confirm no regressions**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest -q`
Expected: all tests pass (61 existing minus the 1 renamed/replaced, plus 1 new = same or higher total, 0 failures).

- [ ] **Step 6: Commit**

```bash
git add services/hostel-service/hostel/views.py services/hostel-service/hostel/tests/test_available_template.py
git commit -m "fix(hostel-service): bulk-upload CSV template emits one row per free seat, not per room"
```

---

## Task 2: Admin — edit room capacity

**Files:**
- Modify: `services/hostel-service/hostel/serializers.py` (add `RoomCapacityUpdateSerializer`)
- Modify: `services/hostel-service/hostel/views.py` (add `RoomDetailView`)
- Modify: `services/hostel-service/hostel/urls.py` (add route + import)
- Create: `services/hostel-service/hostel/tests/test_room_capacity_update.py`

**Interfaces:**
- Consumes: `Room` model (`services/hostel-service/hostel/models.py:41-58`, fields `capacity`, `occupied_count`), `RoomSerializer` (`hostel/serializers.py:36-51`), `role_required` (`suerp_common.permissions`), `ok`/`fail` (`suerp_common.envelope`).
- Produces: `RoomCapacityUpdateSerializer` (validates `{"capacity": int}`, `min_value=1`), `RoomDetailView` (APIView, `patch` method) at `PATCH /api/v1/hostel/rooms/<uuid:pk>`. Later frontend task calls this exact path with body `{"capacity": <int>}` and expects the same `RoomSerializer` shape back on success, or a 400 with `{"errors": {"capacity": [...]}}`-style DRF validation errors, or a top-level `fail(message, status=400)` for the below-occupancy business-rule rejection.

- [ ] **Step 1: Write the failing tests**

Create `services/hostel-service/hostel/tests/test_room_capacity_update.py`:

```python
"""PATCH /api/v1/hostel/rooms/<id> — admin edits room capacity.

Increasing is always allowed. Decreasing below the room's current
occupied_count is rejected with a 400 — a room can never show fewer seats
than students already living in it.
"""

import uuid

import pytest

pytestmark = pytest.mark.django_db

from hostel.models import Room  # noqa: E402
from hostel.tests.test_allocate import _auth_client, _make_room  # noqa: E402


def test_admin_increases_capacity():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1, room_no="101")
    client = _auth_client(tenant_id, role="admin")

    response = client.patch(
        f"/api/v1/hostel/rooms/{room.id}", {"capacity": 4}, format="json"
    )

    assert response.status_code == 200, response.content
    body = response.json()["data"]
    assert body["capacity"] == 4

    room.refresh_from_db()
    assert room.capacity == 4


def test_admin_decreases_capacity_above_occupied_count():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=4, occupied_count=1, room_no="101")
    client = _auth_client(tenant_id, role="admin")

    response = client.patch(
        f"/api/v1/hostel/rooms/{room.id}", {"capacity": 2}, format="json"
    )

    assert response.status_code == 200, response.content
    room.refresh_from_db()
    assert room.capacity == 2


def test_rejects_capacity_below_occupied_count():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=4, occupied_count=3, room_no="101")
    client = _auth_client(tenant_id, role="admin")

    response = client.patch(
        f"/api/v1/hostel/rooms/{room.id}", {"capacity": 2}, format="json"
    )

    assert response.status_code == 400, response.content
    room.refresh_from_db()
    assert room.capacity == 4  # unchanged


def test_warden_forbidden_from_updating_capacity():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    client = _auth_client(tenant_id, role="warden")

    response = client.patch(
        f"/api/v1/hostel/rooms/{room.id}", {"capacity": 4}, format="json"
    )

    assert response.status_code == 403


def test_404_for_room_in_other_tenant():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    room = _make_room(tenant_a, capacity=2, occupied_count=0, room_no="101")
    client = _auth_client(tenant_b, role="admin")

    response = client.patch(
        f"/api/v1/hostel/rooms/{room.id}", {"capacity": 4}, format="json"
    )

    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_room_capacity_update.py -v`
Expected: FAIL with 404 (no such URL) for every test — `RoomDetailView` and its route don't exist yet.

- [ ] **Step 3: Add `RoomCapacityUpdateSerializer`**

In `services/hostel-service/hostel/serializers.py`, add after `RoomCreateSerializer` (after line 70):

```python
class RoomCapacityUpdateSerializer(serializers.Serializer):
    capacity = serializers.IntegerField(min_value=1)
```

- [ ] **Step 4: Add `RoomDetailView`**

In `services/hostel-service/hostel/views.py`, add the import `RoomCapacityUpdateSerializer` to the existing `from hostel.serializers import (...)` block, and add this view right after `RoomListCreateView` (after line 167, before the blank line at 169):

```python
class RoomDetailView(APIView):
    """PATCH /api/v1/hostel/rooms/<id> — admin edits room capacity.

    Increasing is always allowed. Decreasing below the room's current
    occupied_count is rejected — a room can never show fewer seats than
    students already living in it.
    """

    permission_classes = [role_required("admin")]

    def patch(self, request, pk):
        serializer = RoomCapacityUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid capacity payload.", errors=serializer.errors, status=400)

        room = get_object_or_404(Room.objects.all(), id=pk)
        new_capacity = serializer.validated_data["capacity"]
        if new_capacity < room.occupied_count:
            return fail(
                f"Capacity cannot be lower than current occupancy ({room.occupied_count}).",
                status=400,
            )

        room.capacity = new_capacity
        room.save(update_fields=["capacity"])
        return ok(RoomSerializer(room).data, message="Room capacity updated.")
```

- [ ] **Step 5: Wire the route**

In `services/hostel-service/hostel/urls.py`, add `RoomDetailView` to the import list (alphabetical, after `RejectRoomRequestView`), and add this path right after the `"rooms"` path (after line 31):

```python
    path("rooms/<uuid:pk>", RoomDetailView.as_view(), name="room-detail"),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_room_capacity_update.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 7: Run the full hostel-service suite to confirm no regressions**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest -q`
Expected: all tests pass, 0 failures.

- [ ] **Step 8: Commit**

```bash
git add services/hostel-service/hostel/serializers.py services/hostel-service/hostel/views.py services/hostel-service/hostel/urls.py services/hostel-service/hostel/tests/test_room_capacity_update.py
git commit -m "feat(hostel-service): add PATCH /rooms/{id} for admin to edit room capacity"
```

---

## Task 3: Warden — release an allocation

**Files:**
- Modify: `services/hostel-service/hostel/views.py` (add `ReleaseAllocationView`)
- Modify: `services/hostel-service/hostel/urls.py` (add route + import)
- Create: `services/hostel-service/hostel/tests/test_release_allocation.py`

**Interfaces:**
- Consumes: `Allocation` model (`hostel/models.py:64-84`, `Status.PENDING`/`CONFIRMED`/`RELEASED`), `Room` model, `role_required`, `ok`/`fail`, `publish_event` (`suerp_common.outbox`) — reuses the exact `hostel.allocation.released` payload shape from `hostel/consumers.py:_apply_outcome`'s FAILED branch (`allocation_id`, `student_user_code`, `room_id`, all as `str(...)`).
- Produces: `ReleaseAllocationView` (APIView, `post` method) at `POST /api/v1/hostel/allocations/<uuid:pk>/release`. No later task depends on this.

- [ ] **Step 1: Write the failing tests**

Create `services/hostel-service/hostel/tests/test_release_allocation.py`:

```python
"""POST /api/v1/hostel/allocations/<id>/release — warden manually releases an
allocation (student moved out, mistake, etc.), independent of the automated
payment-saga release path in hostel/consumers.py. Frees the room seat the
same way (occupied_count -= 1, status -> released) but triggered directly
by a warden/admin instead of a payment-failed/timeout event.
"""

import uuid

import pytest

pytestmark = pytest.mark.django_db

from hostel.models import Allocation, Room  # noqa: E402
from hostel.tests.test_allocate import _auth_client, _make_room  # noqa: E402
from suerp_common.outbox import OutboxEvent  # noqa: E402


def _make_allocation(tenant_id, room, student_user_code="STU001", status="confirmed"):
    return Allocation.all_objects.create(
        tenant_id=tenant_id,
        room=room,
        student_user_code=student_user_code,
        status=status,
    )


def test_warden_releases_confirmed_allocation_frees_seat():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1, room_no="101")
    allocation = _make_allocation(tenant_id, room, status="confirmed")
    client = _auth_client(tenant_id, role="warden")

    response = client.post(f"/api/v1/hostel/allocations/{allocation.id}/release")

    assert response.status_code == 200, response.content
    body = response.json()["data"]
    assert body["status"] == "released"

    allocation.refresh_from_db()
    assert allocation.status == "released"
    room.refresh_from_db()
    assert room.occupied_count == 0

    event = OutboxEvent.objects.get(tenant_id=tenant_id, type="hostel.allocation.released")
    assert event.payload["allocation_id"] == str(allocation.id)
    assert event.payload["room_id"] == str(room.id)


def test_warden_releases_pending_allocation():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1, room_no="101")
    allocation = _make_allocation(tenant_id, room, status="pending")
    client = _auth_client(tenant_id, role="warden")

    response = client.post(f"/api/v1/hostel/allocations/{allocation.id}/release")

    assert response.status_code == 200, response.content
    allocation.refresh_from_db()
    assert allocation.status == "released"
    room.refresh_from_db()
    assert room.occupied_count == 0


def test_admin_can_also_release():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1, room_no="101")
    allocation = _make_allocation(tenant_id, room, status="confirmed")
    client = _auth_client(tenant_id, role="admin")

    response = client.post(f"/api/v1/hostel/allocations/{allocation.id}/release")

    assert response.status_code == 200, response.content


def test_rejects_already_released_allocation():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    allocation = _make_allocation(tenant_id, room, status="released")
    client = _auth_client(tenant_id, role="warden")

    response = client.post(f"/api/v1/hostel/allocations/{allocation.id}/release")

    assert response.status_code == 400
    room.refresh_from_db()
    assert room.occupied_count == 0  # unchanged, no double-decrement


def test_student_forbidden_from_releasing():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=1, room_no="101")
    allocation = _make_allocation(tenant_id, room, status="confirmed")
    client = _auth_client(tenant_id, role="student", user_id="STU001")

    response = client.post(f"/api/v1/hostel/allocations/{allocation.id}/release")

    assert response.status_code == 403


def test_404_for_allocation_in_other_tenant():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    room = _make_room(tenant_a, capacity=2, occupied_count=1, room_no="101")
    allocation = _make_allocation(tenant_a, room, status="confirmed")
    client = _auth_client(tenant_b, role="warden")

    response = client.post(f"/api/v1/hostel/allocations/{allocation.id}/release")

    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_release_allocation.py -v`
Expected: FAIL with 404 (no such URL) for every test.

- [ ] **Step 3: Add `ReleaseAllocationView`**

In `services/hostel-service/hostel/views.py`, add `from suerp_common.outbox import publish_event` to the imports (it isn't imported in this file yet — `hostel/consumers.py` imports it separately). Then add this view right after `AllocationListView` (after line 177, before `RoomRequestListCreateView`):

```python
class ReleaseAllocationView(APIView):
    """POST /api/v1/hostel/allocations/<id>/release — warden manually releases
    an allocation. Same accounting as the automated payment-saga release path
    in hostel/consumers.py (_apply_outcome's FAILED branch): frees the room
    seat under a row lock and emits the same hostel.allocation.released event,
    just triggered directly instead of by a payment-failed/timeout event.
    """

    permission_classes = [role_required("warden", "admin")]

    def post(self, request, pk):
        allocation = get_object_or_404(Allocation.objects.all(), id=pk)
        if allocation.status == Allocation.Status.RELEASED:
            return fail("Allocation is already released.", status=400)

        tenant_id = allocation.tenant_id
        with transaction.atomic():
            room = Room.objects.select_for_update().get(pk=allocation.room_id)
            allocation.status = Allocation.Status.RELEASED
            allocation.save(update_fields=["status"])
            room.occupied_count = max(0, room.occupied_count - 1)
            room.save(update_fields=["occupied_count"])
            publish_event(
                "hostel.allocation.released",
                tenant_id=tenant_id,
                payload={
                    "allocation_id": str(allocation.id),
                    "student_user_code": allocation.student_user_code,
                    "room_id": str(allocation.room_id),
                },
            )

        return ok(AllocationSerializer(allocation).data, message="Allocation released.")
```

- [ ] **Step 4: Wire the route**

In `services/hostel-service/hostel/urls.py`, add `ReleaseAllocationView` to the import list (alphabetical, after `RejectRoomRequestView` — before `RoomDetailView` if Task 2 already landed), and add this path right after the `"allocations"` path (after the `allocation-list` path, before `allocations/import-logs`):

```python
    path(
        "allocations/<uuid:pk>/release",
        ReleaseAllocationView.as_view(),
        name="allocation-release",
    ),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest hostel/tests/test_release_allocation.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 6: Run the full hostel-service suite to confirm no regressions**

Run: `docker compose -f infra/docker-compose.yml exec -e DATABASE_URL="postgresql://suerp:suerp@suerp-postgres:5432/hostel" hostel-service pytest -q`
Expected: all tests pass, 0 failures.

- [ ] **Step 7: Commit**

```bash
git add services/hostel-service/hostel/views.py services/hostel-service/hostel/urls.py services/hostel-service/hostel/tests/test_release_allocation.py
git commit -m "feat(hostel-service): add POST /allocations/{id}/release for warden to manually release an allocation"
```

---

## Task 4: Frontend — admin capacity editor

**Files:**
- Modify: `frontend/su-erp-web/src/app/(dashboard)/admin/page.tsx`

**Interfaces:**
- Consumes: `PATCH /api/v1/hostel/rooms/{id}` from Task 2 (body `{"capacity": <int>}`, returns updated room or 400 on below-occupancy rejection), the existing `Room` interface (`id`, `block_name`, `room_no`, `capacity`, `occupied_count`, already declared in this file), the existing `api.patch` helper (verify it exists in `frontend/su-erp-web/src/lib/api.ts` before using — if missing, add it following the exact pattern of the existing `api.post`/`api.get`), `fieldErrorMessage`/`errMsg` helpers already used elsewhere in this file, `loadRooms` (already passed as `onCreated` to `CreateRoom`, reuse it to refresh after a capacity edit).
- Produces: no new exported symbols — this is a UI-only change inside the existing "Rooms" `DataPanel` table.

- [ ] **Step 1: Verify `api.patch` exists**

Read `frontend/su-erp-web/src/lib/api.ts` and check for an exported `patch` method on the `api` object (sibling to `api.get`/`api.post`). If missing, add it following the exact same fetch-wrapper pattern as `api.post` (same headers, same auth-token injection, same envelope-unwrapping/error-throwing behavior), only with method `"PATCH"`.

- [ ] **Step 2: Add capacity-edit state and handler to the Rooms table**

In `frontend/su-erp-web/src/app/(dashboard)/admin/page.tsx`, inside the component that renders the "Rooms" `DataPanel` (the one currently at lines 563-590), add local state for the in-progress edit and a handler function above the `return`:

```tsx
const [editingCapacity, setEditingCapacity] = useState<Record<string, string>>({});
const [capacityError, setCapacityError] = useState<string | null>(null);

async function updateCapacity(roomId: string) {
  const value = editingCapacity[roomId];
  if (!value) return;
  setCapacityError(null);
  try {
    await api.patch(`/api/v1/hostel/rooms/${roomId}`, { capacity: Number(value) });
    setEditingCapacity((prev) => {
      const next = { ...prev };
      delete next[roomId];
      return next;
    });
    loadRooms();
  } catch (err) {
    setCapacityError(fieldErrorMessage(err) ?? errMsg(err));
  }
}
```

- [ ] **Step 3: Replace the read-only occupancy cell with an editable one**

Replace the existing table body (lines 578-587):

```tsx
            {rooms.map((r) => (
              <Row key={r.id}>
                <TD className="font-medium">{r.block_name}</TD>
                <TD>{r.room_no}</TD>
                <TD className="text-muted">
                  {r.occupied_count}/{r.capacity}
                </TD>
              </Row>
            ))}
```

with:

```tsx
            {rooms.map((r) => (
              <Row key={r.id}>
                <TD className="font-medium">{r.block_name}</TD>
                <TD>{r.room_no}</TD>
                <TD className="text-muted">
                  <span>{r.occupied_count}/</span>
                  <Input
                    className="inline-block w-16"
                    type="number"
                    min={1}
                    value={editingCapacity[r.id] ?? String(r.capacity)}
                    onChange={(e) =>
                      setEditingCapacity((prev) => ({ ...prev, [r.id]: e.target.value }))
                    }
                  />
                  <Button
                    type="button"
                    onClick={() => updateCapacity(r.id)}
                    disabled={
                      editingCapacity[r.id] === undefined ||
                      Number(editingCapacity[r.id]) === r.capacity
                    }
                  >
                    Save
                  </Button>
                </TD>
              </Row>
            ))}
```

And add `{capacityError && <Alert tone="error">{capacityError}</Alert>}` immediately above the `<Table>` in that same `DataPanel`.

- [ ] **Step 4: Rebuild and restart the frontend container**

Run: `docker compose -f infra/docker-compose.yml build frontend && docker compose -f infra/docker-compose.yml up -d frontend`

- [ ] **Step 5: Manually verify in the browser**

Log in as admin (`rajesh.sharma@pdpmiiitdmj.ac.in` / `Passw0rd123`, institution slug `pdpmiiitdmj`), go to the Rooms table, change a capacity value, click Save, confirm the row updates and no error banner appears. Then try setting a capacity below the room's current `occupied_count` and confirm the error banner shows the exact backend message.

- [ ] **Step 6: Commit**

```bash
git add frontend/su-erp-web/src/app/"(dashboard)"/admin/page.tsx frontend/su-erp-web/src/lib/api.ts
git commit -m "feat(admin-ui): add inline room-capacity editor to Rooms table"
```

---

## Task 5: Frontend — warden release button

**Files:**
- Modify: `frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx`

**Interfaces:**
- Consumes: `POST /api/v1/hostel/allocations/{id}/release` from Task 3 (no body, returns updated allocation or 400 if already released), the existing `Allocation` interface (already has `id`, `student_user_code`, `room_id`, `room_name`, `status` — fixed in the prior session's bug fix), `loadAllocations` (already defined in `WardenContent`, currently called via `useEffect`/on mount — reuse to refresh after release).
- Produces: no new exported symbols.

- [ ] **Step 1: Broaden the pending-allocations query to include confirmed**

In `frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx`, find `loadAllocations` (around line 70-81) and change the query from `?status=pending` to fetch both statuses. Since the backend's `AllocationListView` only accepts a single `status` value, fetch both and merge:

```tsx
  const loadAllocations = useCallback(async () => {
    setAllocLoading(true);
    setAllocError(null);
    try {
      const [pendingData, confirmedData] = await Promise.all([
        api.get("/api/v1/hostel/allocations?status=pending"),
        api.get("/api/v1/hostel/allocations?status=confirmed"),
      ]);
      setAllocations([
        ...listItems<Allocation>(pendingData),
        ...listItems<Allocation>(confirmedData),
      ]);
    } catch (e) {
      setAllocError(errMsg(e));
    } finally {
      setAllocLoading(false);
    }
  }, []);
```

- [ ] **Step 2: Add a release handler and button to the allocations table**

Add this handler inside `WardenContent`, above the `return`:

```tsx
  const [releaseError, setReleaseError] = useState<string | null>(null);

  async function releaseAllocation(id: string) {
    setReleaseError(null);
    try {
      await api.post(`/api/v1/hostel/allocations/${id}/release`, {});
      await loadAllocations();
    } catch (err) {
      setReleaseError(errMsg(err));
    }
  }
```

Replace the "Pending hostel allocations" `DataPanel` (lines 137-164) title and table body:

```tsx
      <DataPanel
        title="Hostel allocations"
        loading={allocLoading}
        error={allocError}
        isEmpty={allocations.length === 0}
        emptyLabel="No active allocations."
      >
        {releaseError && <Alert tone="error">{releaseError}</Alert>}
        <Table>
          <THead>
            <HeaderRow>
              <TH>Student</TH>
              <TH>Room</TH>
              <TH>Status</TH>
              <TH />
            </HeaderRow>
          </THead>
          <TBody>
            {allocations.map((a) => (
              <Row key={a.id}>
                <TD className="font-mono text-[12px]">{a.student_user_code}</TD>
                <TD className="font-medium">{a.room_name}</TD>
                <TD>
                  <StatusPill status={a.status} />
                </TD>
                <TD>
                  <Button type="button" onClick={() => releaseAllocation(a.id)}>
                    Release
                  </Button>
                </TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>
```

- [ ] **Step 3: Rebuild and restart the frontend container**

Run: `docker compose -f infra/docker-compose.yml build frontend && docker compose -f infra/docker-compose.yml up -d frontend`

- [ ] **Step 4: Manually verify in the browser**

Log in as warden (`suresh.verma@pdpmiiitdmj.ac.in` / `Passw0rd123`, institution slug `pdpmiiitdmj`), confirm both pending and confirmed allocations show in the table, click Release on one, confirm it disappears from the list (or reflects the released state) with no error.

- [ ] **Step 5: Commit**

```bash
git add frontend/su-erp-web/src/app/"(dashboard)"/warden/page.tsx
git commit -m "feat(warden-ui): show confirmed allocations alongside pending, add manual Release action"
```

---

## Self-Review Notes

- **Spec coverage:** All 3 spec items have tasks (Task 1 = CSV template, Tasks 2+4 = capacity edit backend+frontend, Tasks 3+5 = release backend+frontend). Spec's explicit out-of-scope item (student relocation / swap) is not touched.
- **Type consistency:** `Allocation` interface fields (`student_user_code`, `room_id`, `room_name`, `status`) match the already-fixed frontend interface from the prior bug-fix session — verified against the live file before writing Task 5. `RoomSerializer`/`AllocationSerializer` field names in Tasks 2/3 match `hostel/serializers.py` exactly as read from the current file.
- **No placeholders:** every step has literal file paths, complete code blocks, and exact commands with expected output.
