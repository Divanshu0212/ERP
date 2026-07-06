# Room Requests, Warden Approval, Fee Structures & Payment Receipts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Students request a specific room; a warden approves (choosing a fee) or
rejects the request. Approval reuses the existing allocation/payment saga
unchanged, except the invoice amount now comes from a warden-configurable
`FeeStructure` instead of a hardcoded constant. On successful payment, a signed,
verifiable PDF receipt (with university name, amount, purpose, QR code) is
generated and can be downloaded by the student and verified by warden/admin.

**Architecture:** hostel-service gets a new `RoomRequest` model (mirrors the
existing `LeaveRequest` three-state shape) plus student-facing
create/list-own endpoints and warden-facing list-pending/approve/reject
endpoints. Approval calls the existing `create_allocation()` unchanged, extended
with an optional `fee_structure_id` parameter that flows through the
`hostel.allocation.requested` event payload alongside a `university_name`
resolved synchronously (same pattern as the existing `resolve_user_by_email`
call) from auth-service's `GET /api/v1/auth/institution` endpoint, using the
approving warden's own bearer token. finance-service's consumer reads
`fee_structure_id`/`university_name` off that event instead of the hardcoded
`HOSTEL_FEE_AMOUNT`, and stores `university_name` denormalized on `Invoice`.
finance-service gets a `FeeStructure` admin CRUD endpoint (wiring up the
existing-but-unused model) and Receipt generation happens synchronously inside
`PayView`'s existing atomic block on payment success: a PDF (reportlab) with an
embedded QR code (qrcode) encoding a full verify-page URL, and an HMAC-signed
token (new `RECEIPT_HMAC_SECRET` setting, separate from `JWT_SIGNING_KEY`) are
generated once and the PDF bytes stored in a new `Receipt.pdf_data` field — no
persisted file, no new media infra. A new frontend page renders the verify
result behind existing warden/admin login.

**Tech Stack:** Django 5 + DRF (hostel-service, finance-service), `reportlab`
(new dependency, PDF rendering), `qrcode[pil]` (new dependency, QR generation),
Python stdlib `hmac`/`hashlib` (token signing), Next.js/TypeScript frontend.

## Global Constraints

- Every model in both services is a `suerp_common.tenancy.TenantModel`
  subclass; request-path code uses the tenant-scoped `objects` manager
  (`get_current_tenant()` in hostel-service, `request.tenant_id` in
  finance-service — each service's own existing convention, don't mix them).
  Consumer/background code (no request context) MUST use `all_objects` with
  an explicit `tenant_id`, per both existing consumer docstrings.
- Response envelope for JSON endpoints is `{ success, data, message, errors }`
  via `suerp_common.envelope.ok`/`fail`. The PDF-download endpoint is the one
  exception — it returns a raw `HttpResponse` with `Content-Type:
  application/pdf`, matching the CSV-template endpoint precedent from the
  prior plan (`hostel/views.py: AvailableRoomsTemplateView`).
- All hostel routes stay under `/api/v1/hostel/...`, all finance routes under
  `/api/v1/finance/...` — existing gateway routing, no nginx changes needed.
- State change + `publish_event(...)` calls MUST stay inside the same
  `transaction.atomic()` block wherever either appears (transactional-outbox
  guarantee, followed everywhere in both services today).
- `@idempotent` (from `suerp_common.inbox`) wraps every event-consumer
  handler, outermost.
- No new dependency may be added without updating the owning service's
  `requirements.txt` (`reportlab`, `qrcode` go in
  `services/finance-service/requirements.txt`).
- Follow each service's existing test patterns exactly:
  `_auth_client`/`_make_room`/`_make_block`
  (`hostel/tests/test_allocate.py`) for hostel-service,
  `pytest.mark.django_db` for both.

---

### Task 1: hostel-service — `RoomRequest` model + student create/list endpoints

**Files:**
- Modify: `services/hostel-service/hostel/models.py` (add `RoomRequest` after
  `LeaveRequest`, currently ending at line 152)
- Create: `services/hostel-service/hostel/migrations/0005_roomrequest.py`
- Modify: `services/hostel-service/hostel/serializers.py`
- Modify: `services/hostel-service/hostel/views.py`
- Modify: `services/hostel-service/hostel/urls.py`
- Test: Create `services/hostel-service/hostel/tests/test_room_requests.py`

**Interfaces:**
- Consumes: `Room` model (`hostel/models.py:41-61`), `role_required` (from
  `suerp_common.permissions`), `get_current_tenant()` (from
  `suerp_common.tenancy`).
- Produces: `RoomRequest` model with fields `id`, `student_id`, `room` (FK),
  `status` (`RoomRequest.Status.PENDING/APPROVED/REJECTED`), `requested_on`,
  `decided_on` (nullable), `decided_by` (nullable UUID),
  `rejection_reason` (blank-default CharField). Consumed by Task 2's approval
  view.

- [ ] **Step 1: Write the failing test for student room-request creation**

Create `services/hostel-service/hostel/tests/test_room_requests.py`:

```python
"""Student room requests: create + list-own (hostel/models.py: RoomRequest).

Warden approve/reject endpoints are covered in test_room_request_approval.py
(Task 2) — this file only covers the student-facing half.
"""

import uuid

import pytest

pytestmark = pytest.mark.django_db

from hostel.models import RoomRequest
from hostel.tests.test_allocate import _auth_client, _make_room


def test_student_can_create_room_request():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    student_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="student", user_id=student_id)

    response = client.post(
        "/api/v1/hostel/room-requests",
        {"room_id": str(room.id)},
        format="json",
    )

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["status"] == "pending"
    assert body["room_id"] == str(room.id)

    req = RoomRequest.all_objects.get(id=body["id"])
    assert req.student_id == student_id
    assert req.tenant_id == tenant_id


def test_student_cannot_request_full_room():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=1, occupied_count=1, room_no="101")
    client = _auth_client(tenant_id, role="student")

    response = client.post(
        "/api/v1/hostel/room-requests",
        {"room_id": str(room.id)},
        format="json",
    )

    assert response.status_code == 400


def test_student_lists_only_own_requests():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=3, occupied_count=0, room_no="101")
    student_a = uuid.uuid4()
    student_b = uuid.uuid4()

    client_a = _auth_client(tenant_id, role="student", user_id=student_a)
    client_a.post("/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json")

    client_b = _auth_client(tenant_id, role="student", user_id=student_b)
    client_b.post("/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json")

    response = client_a.get("/api/v1/hostel/room-requests/mine")
    assert response.status_code == 200
    items = response.json()["data"]["results"] if "results" in response.json()["data"] else response.json()["data"]
    student_ids = {item.get("student_id") for item in items} if items and "student_id" in items[0] else None
    assert len(items) == 1


def test_warden_role_forbidden_from_student_create():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/room-requests",
        {"room_id": str(room.id)},
        format="json",
    )

    assert response.status_code == 403
```

Note `_auth_client` (`hostel/tests/test_allocate.py:40-44`) already accepts
`**kwargs` forwarded to `_make_token`, and `_make_token` (lines 31-37) already
accepts `user_id=None` — so `_auth_client(tenant_id, role="student",
user_id=student_id)` works with zero changes to the existing test helper.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/hostel-service && ../../.venv/bin/pytest hostel/tests/test_room_requests.py -v`
Expected: FAIL — `ImportError: cannot import name 'RoomRequest'`.

- [ ] **Step 3: Add the `RoomRequest` model**

In `services/hostel-service/hostel/models.py`, add directly after the
`LeaveRequest` class (after its `__str__` method, before `class Complaint`):

```python
class RoomRequest(TenantModel):
    """A student's request to be allocated a specific room, awaiting warden
    approval. Distinct from ``Allocation`` — this is the pre-approval intent;
    approving one calls ``create_allocation()`` (hostel/services.py), which
    creates the actual ``Allocation`` and starts the existing payment saga
    unchanged.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student_id = models.UUIDField()
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="requests")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    requested_on = models.DateTimeField(auto_now_add=True)
    decided_on = models.DateTimeField(null=True, blank=True)
    # Reference to auth-service's User table (the warden who approved/rejected).
    # Bare UUID — no cross-service FK (DB-per-service).
    decided_by = models.UUIDField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        ordering = ["-requested_on"]

    def __str__(self):
        return f"RoomRequest {self.id} ({self.status})"
```

- [ ] **Step 4: Generate and apply the migration**

Run: `cd services/hostel-service && ../../.venv/bin/python manage.py makemigrations hostel`
Expected: creates a migration file — rename it to
`hostel/migrations/0005_roomrequest.py` if Django picks a different name.

Run: `../../.venv/bin/python manage.py migrate hostel`
Expected: applies cleanly.

- [ ] **Step 5: Add serializers**

In `services/hostel-service/hostel/serializers.py`, add at the end of the file:

```python
class RoomRequestCreateSerializer(serializers.Serializer):
    room_id = serializers.UUIDField()


class RoomRequestSerializer(serializers.ModelSerializer):
    room_id = serializers.UUIDField(source="room.id", read_only=True)
    room_name = serializers.SerializerMethodField()

    class Meta:
        model = RoomRequest
        fields = [
            "id",
            "student_id",
            "room_id",
            "room_name",
            "status",
            "requested_on",
            "decided_on",
            "rejection_reason",
        ]
        read_only_fields = fields

    def get_room_name(self, obj):
        return f"{obj.room.block.name} - {obj.room.room_no}"
```

And add `RoomRequest` to the existing model import at the top of the file:

```python
from hostel.models import (
    Allocation,
    AllocationImportBatch,
    AllocationImportRow,
    Block,
    Room,
    RoomRequest,
)
```

- [ ] **Step 6: Add the student-facing views**

In `services/hostel-service/hostel/views.py`, add the import
(`RoomRequest` to the existing `from hostel.models import (...)` line, and the
two new serializers to the existing `from hostel.serializers import (...)`
block), then add these two classes after `AllocationListView` (currently ends
at line 131, right before `class AllocationImportLogListView`):

```python
class RoomRequestCreateView(APIView):
    """POST /api/v1/hostel/room-requests — student requests a specific room.

    Only checks the room has free capacity at request time (same
    ``is_available`` check ``create_allocation`` uses) — this is advisory,
    not a reservation; the authoritative capacity check + row lock happens
    again in ``create_allocation`` at approval time, so a room that fills up
    between request and approval correctly 400s the approval instead.
    """

    permission_classes = [role_required("student")]

    def post(self, request):
        serializer = RoomRequestCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid room request payload.", errors=serializer.errors, status=400)

        room = get_object_or_404(Room.objects.all(), id=serializer.validated_data["room_id"])
        if not room.is_available:
            return fail("Room is at full capacity.", status=400)

        room_request = RoomRequest.objects.create(
            tenant_id=get_current_tenant(),
            student_id=request.user.id,
            room=room,
            status=RoomRequest.Status.PENDING,
        )
        return ok(
            RoomRequestSerializer(room_request).data,
            message="Room request submitted.",
            status=201,
        )


class MyRoomRequestsView(ListAPIView):
    """GET /api/v1/hostel/room-requests/mine — the caller's own requests."""

    serializer_class = RoomRequestSerializer
    permission_classes = [role_required("student")]

    def get_queryset(self):
        return RoomRequest.objects.filter(student_id=self.request.user.id).order_by(
            "-requested_on"
        )
```

- [ ] **Step 7: Wire the URLs**

In `services/hostel-service/hostel/urls.py`, add the import and two routes.
Note: Task 2 will later replace `RoomRequestCreateView` with a merged
`RoomRequestListCreateView` (adding a warden-facing GET to the same path) —
this step's `RoomRequestCreateView` stands on its own for now and its tests
pass unmodified once Task 2 lands, since Task 2 preserves the exact same POST
behavior on the same path.

```python
from hostel.views import (
    AllocateBulkView,
    AllocateView,
    AllocationImportLogDetailView,
    AllocationImportLogListView,
    AllocationListView,
    AvailableRoomsTemplateView,
    AvailableRoomsView,
    BlockListCreateView,
    MyRoomRequestsView,
    RoomListCreateView,
    RoomRequestCreateView,
)

urlpatterns = [
    # ... existing entries unchanged ...
    path("room-requests/mine", MyRoomRequestsView.as_view(), name="room-request-mine"),
    path("room-requests", RoomRequestCreateView.as_view(), name="room-request-create"),
]
```

Add these two new `path(...)` lines at the end of the existing
`urlpatterns` list, after the `allocations/import-logs/<uuid:pk>` entry.
`room-requests/mine` is listed first — both are literal (non-parameterized)
segments so Django tries them in list order; listing the more specific path
first is for readability, not correctness, but keep it as written since
Task 2 relies on this same ordering when it adds two more `room-requests/...`
routes.

- [ ] **Step 8: Run test to verify it passes**

Run: `cd services/hostel-service && ../../.venv/bin/pytest hostel/tests/test_room_requests.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 9: Run the full hostel-service test suite**

Run: `../../.venv/bin/pytest hostel/ -v`
Expected: all tests PASS (51 previously + 4 new = 55).

- [ ] **Step 10: Commit**

```bash
git add services/hostel-service/hostel/models.py \
        services/hostel-service/hostel/migrations/ \
        services/hostel-service/hostel/serializers.py \
        services/hostel-service/hostel/views.py \
        services/hostel-service/hostel/urls.py \
        services/hostel-service/hostel/tests/test_room_requests.py
git commit -m "feat(hostel): add student room-request create/list endpoints"
```

---

### Task 2: hostel-service — `create_allocation` fee/university params + warden approve/reject

**Files:**
- Modify: `services/hostel-service/hostel/services.py:26-59`
- Modify: `services/hostel-service/hostel/views.py`
- Modify: `services/hostel-service/hostel/urls.py`
- Test: Create `services/hostel-service/hostel/tests/test_room_request_approval.py`

**Interfaces:**
- Consumes: `RoomRequest` (Task 1), `resolve_user_by_email` /
  `LookupFailed` pattern from `hostel/lookups.py` (used as the template for a
  new institution lookup, not reused directly — different endpoint/shape).
- Produces: `create_allocation(room_id, student_id, tenant_id,
  fee_structure_id=None, university_name="")`. The
  `hostel.allocation.requested` event payload gains two new optional keys:
  `fee_structure_id` (str UUID or `None`) and `university_name` (str,
  possibly empty). Task 4 (finance consumer) reads these exact keys.

- [ ] **Step 1: Write the failing test for approval**

Create `services/hostel-service/hostel/tests/test_room_request_approval.py`:

```python
"""Warden approve/reject on a student RoomRequest (hostel/models.py:
RoomRequest). Approval calls the existing create_allocation() unchanged (same
lock/capacity-check/atomic-commit/outbox path AllocateView already uses),
extended with fee_structure_id/university_name flowing into the
hostel.allocation.requested event payload for finance-service to consume.
"""

import uuid
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db

from hostel.models import Allocation, RoomRequest
from hostel.tests.test_allocate import _auth_client, _make_room
from suerp_common.outbox import OutboxEvent


@patch("hostel.views.requests.get")
def test_warden_approves_request_creates_allocation_with_fee_and_university(mock_get):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    student_id = uuid.uuid4()

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

    fee_structure_id = uuid.uuid4()
    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.post(
        f"/api/v1/hostel/room-requests/{request_id}/approve",
        {"fee_structure_id": str(fee_structure_id)},
        format="json",
    )

    assert response.status_code == 200, response.content
    body = response.json()["data"]
    assert body["status"] == "approved"

    req = RoomRequest.all_objects.get(id=request_id)
    assert req.status == "approved"
    assert req.decided_on is not None

    allocation = Allocation.all_objects.get(student_id=student_id, tenant_id=tenant_id)
    assert allocation.status == "pending"

    event = OutboxEvent.all_objects.get(
        tenant_id=tenant_id, type="hostel.allocation.requested"
    )
    assert event.payload["fee_structure_id"] == str(fee_structure_id)
    assert event.payload["university_name"] == "Test University"


def test_warden_rejects_request():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    student_client = _auth_client(tenant_id, role="student")
    create_response = student_client.post(
        "/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json"
    )
    request_id = create_response.json()["data"]["id"]

    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.post(
        f"/api/v1/hostel/room-requests/{request_id}/reject",
        {"rejection_reason": "Room reserved for staff."},
        format="json",
    )

    assert response.status_code == 200, response.content
    req = RoomRequest.all_objects.get(id=request_id)
    assert req.status == "rejected"
    assert req.rejection_reason == "Room reserved for staff."
    assert Allocation.all_objects.filter(tenant_id=tenant_id).count() == 0


def test_student_role_forbidden_from_approve():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    student_client = _auth_client(tenant_id, role="student")
    create_response = student_client.post(
        "/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json"
    )
    request_id = create_response.json()["data"]["id"]

    response = student_client.post(
        f"/api/v1/hostel/room-requests/{request_id}/approve",
        {"fee_structure_id": str(uuid.uuid4())},
        format="json",
    )
    assert response.status_code == 403


def test_pending_list_shows_only_pending():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    student_client = _auth_client(tenant_id, role="student")
    student_client.post("/api/v1/hostel/room-requests", {"room_id": str(room.id)}, format="json")

    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.get("/api/v1/hostel/room-requests?status=pending")

    assert response.status_code == 200
    items = response.json()["data"]
    results = items["results"] if isinstance(items, dict) and "results" in items else items
    assert len(results) == 1
    assert results[0]["status"] == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/hostel-service && ../../.venv/bin/pytest hostel/tests/test_room_request_approval.py -v`
Expected: FAIL (404s — no `approve`/`reject`/list-pending routes yet).

- [ ] **Step 3: Extend `create_allocation` with fee/university params**

Modify `services/hostel-service/hostel/services.py`:

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

``fee_structure_id``/``university_name`` are optional, warden-approval-only
extras: they flow straight into the outbox event payload so finance-
service's consumer can price the resulting invoice from a configurable
``FeeStructure`` and stamp the institution's display name onto it, instead
of the old hardcoded ``HOSTEL_FEE_AMOUNT`` constant. Callers that don't pass
them (the plain warden AllocateView/AllocateBulkView path) get ``None``/``""``,
and finance-service's consumer falls back to its existing hardcoded default
in that case — see Task 4.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from hostel.models import Allocation, Room
from suerp_common.outbox import publish_event


class RoomFullError(Exception):
    """Raised when the target room has no free capacity."""


def create_allocation(
    room_id,
    student_id,
    tenant_id,
    fee_structure_id=None,
    university_name="",
) -> Allocation:
    """Reserve a room seat and create a pending Allocation for student_id.

    Raises ``django.http.Http404`` if room_id doesn't resolve to a room in
    this tenant (via get_object_or_404, matching the pre-refactor
    behavior), ``RoomFullError`` if the room has no free capacity.
    """
    with transaction.atomic():
        room = get_object_or_404(Room.objects.select_for_update(), id=room_id)

        if not room.is_available:
            raise RoomFullError(f"Room {room_id} is at full capacity.")

        allocation = Allocation.objects.create(
            tenant_id=tenant_id,
            room=room,
            student_id=student_id,
            status=Allocation.Status.PENDING,
        )

        room.occupied_count += 1
        room.save(update_fields=["occupied_count"])

        publish_event(
            "hostel.allocation.requested",
            tenant_id=tenant_id,
            payload={
                "allocation_id": str(allocation.id),
                "student_id": str(allocation.student_id),
                "room_id": str(room.id),
                "fee_structure_id": str(fee_structure_id) if fee_structure_id else None,
                "university_name": university_name,
            },
        )

        return allocation
```

- [ ] **Step 4: Add the institution-name lookup helper**

In `services/hostel-service/hostel/lookups.py`, add after
`resolve_user_by_email` (after its final `return envelope["data"]` line):

```python
def resolve_institution_name(auth_header: str | None) -> str:
    """Resolve the caller's own institution display name via auth-service.

    Mirrors resolve_user_by_email's forward-the-caller's-token pattern:
    GET /api/v1/auth/institution resolves Institution.objects.get(pk=
    request.user.tenant_id) on auth-service's side from the JWT's own
    ``tenant`` claim, so the forwarded warden token is sufficient — no
    separate service-to-service credential needed. Returns "" (rather than
    raising) on any failure: a missing university name on the receipt is a
    cosmetic degradation, not a reason to fail the approval.
    """
    url = f"{settings.GATEWAY_URL}/api/v1/auth/institution"
    headers = {"Authorization": auth_header} if auth_header else {}

    try:
        response = requests.get(url, headers=headers, timeout=5)
    except requests.RequestException:
        return ""

    if not response.ok:
        return ""

    try:
        envelope = response.json()
    except ValueError:
        return ""

    if not envelope.get("success"):
        return ""

    return envelope.get("data", {}).get("name", "")
```

- [ ] **Step 5: Add serializers for approve/reject**

In `services/hostel-service/hostel/serializers.py`, add after
`RoomRequestSerializer`:

```python
class RoomRequestApproveSerializer(serializers.Serializer):
    fee_structure_id = serializers.UUIDField()


class RoomRequestRejectSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(max_length=500, required=False, default="")
```

- [ ] **Step 6: Replace `RoomRequestCreateView` with a merged list+create view, add approve/reject**

In `services/hostel-service/hostel/views.py`, **delete** the
`RoomRequestCreateView` class added in Task 1 Step 6 and replace it with this
`RoomRequestListCreateView` (same POST behavior, plus a warden-facing GET on
the same `/api/v1/hostel/room-requests` path — DRF's generic views don't
cleanly support "GET is warden-only, POST is student-only" on one class, so
this dispatches permissions manually per method, same style as
`BlockListCreateView`/`RoomListCreateView` elsewhere in this file):

```python
class RoomRequestListCreateView(APIView):
    """GET /api/v1/hostel/room-requests?status=pending — warden queue.
    POST /api/v1/hostel/room-requests — student requests a specific room.

    ``status`` query param on GET defaults to ``pending`` (the only queue a
    warden normally works from) but accepts any RoomRequest.Status value.
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [role_required("student")()]
        return [role_required("warden", "admin")()]

    def get(self, request):
        status_filter = request.query_params.get("status", RoomRequest.Status.PENDING)
        requests_qs = RoomRequest.objects.filter(status=status_filter).order_by("-requested_on")
        return ok(RoomRequestSerializer(requests_qs, many=True).data)

    def post(self, request):
        serializer = RoomRequestCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid room request payload.", errors=serializer.errors, status=400)

        room = get_object_or_404(Room.objects.all(), id=serializer.validated_data["room_id"])
        if not room.is_available:
            return fail("Room is at full capacity.", status=400)

        room_request = RoomRequest.objects.create(
            tenant_id=get_current_tenant(),
            student_id=request.user.id,
            room=room,
            status=RoomRequest.Status.PENDING,
        )
        return ok(
            RoomRequestSerializer(room_request).data,
            message="Room request submitted.",
            status=201,
        )


class ApproveRoomRequestView(APIView):
    """POST /api/v1/hostel/room-requests/<id>/approve — warden approves.

    Calls create_allocation() unchanged (same lock/capacity-check/atomic-
    commit/outbox path AllocateView uses), passing through the chosen
    fee_structure_id and this tenant's institution name so finance-service's
    consumer can price and label the resulting invoice correctly. Marks the
    RoomRequest approved in the SAME response cycle as create_allocation's own
    atomic block — a RoomRequest left ``pending`` after a successful
    Allocation would be a confusing, permanently-stuck state for the warden UI.
    """

    permission_classes = [role_required("warden", "admin")]

    def post(self, request, pk):
        serializer = RoomRequestApproveSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid approval payload.", errors=serializer.errors, status=400)

        room_request = get_object_or_404(
            RoomRequest.objects.filter(status=RoomRequest.Status.PENDING), id=pk
        )

        university_name = resolve_institution_name(request.META.get("HTTP_AUTHORIZATION"))

        try:
            create_allocation(
                room_request.room_id,
                room_request.student_id,
                get_current_tenant(),
                fee_structure_id=serializer.validated_data["fee_structure_id"],
                university_name=university_name,
            )
        except RoomFullError:
            return fail("Room is no longer available.", status=400)

        room_request.status = RoomRequest.Status.APPROVED
        room_request.decided_on = timezone.now()
        room_request.decided_by = request.user.id
        room_request.save(update_fields=["status", "decided_on", "decided_by"])

        return ok(RoomRequestSerializer(room_request).data, message="Room request approved.")


class RejectRoomRequestView(APIView):
    """POST /api/v1/hostel/room-requests/<id>/reject — warden rejects."""

    permission_classes = [role_required("warden", "admin")]

    def post(self, request, pk):
        serializer = RoomRequestRejectSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid rejection payload.", errors=serializer.errors, status=400)

        room_request = get_object_or_404(
            RoomRequest.objects.filter(status=RoomRequest.Status.PENDING), id=pk
        )
        room_request.status = RoomRequest.Status.REJECTED
        room_request.decided_on = timezone.now()
        room_request.decided_by = request.user.id
        room_request.rejection_reason = serializer.validated_data["rejection_reason"]
        room_request.save(
            update_fields=["status", "decided_on", "decided_by", "rejection_reason"]
        )

        return ok(RoomRequestSerializer(room_request).data, message="Room request rejected.")
```

- [ ] **Step 7: Wire the URLs**

In `services/hostel-service/hostel/urls.py`, replace the
`RoomRequestCreateView` import and its `room-requests` route (added in Task 1
Step 7) with `RoomRequestListCreateView`, and add the approve/reject routes:

```python
from hostel.views import (
    AllocateBulkView,
    AllocateView,
    AllocationImportLogDetailView,
    AllocationImportLogListView,
    AllocationListView,
    ApproveRoomRequestView,
    AvailableRoomsTemplateView,
    AvailableRoomsView,
    BlockListCreateView,
    MyRoomRequestsView,
    RejectRoomRequestView,
    RoomListCreateView,
    RoomRequestListCreateView,
)

urlpatterns = [
    path("allocate", AllocateView.as_view(), name="allocate"),
    path("allocate/bulk", AllocateBulkView.as_view(), name="allocate-bulk"),
    path(
        "rooms/available-template",
        AvailableRoomsTemplateView.as_view(),
        name="rooms-available-template",
    ),
    path("rooms/available", AvailableRoomsView.as_view(), name="rooms-available"),
    path("rooms", RoomListCreateView.as_view(), name="room-list-create"),
    path("blocks", BlockListCreateView.as_view(), name="block-list-create"),
    path("allocations", AllocationListView.as_view(), name="allocation-list"),
    path(
        "allocations/import-logs",
        AllocationImportLogListView.as_view(),
        name="allocation-import-log-list",
    ),
    path(
        "allocations/import-logs/<uuid:pk>",
        AllocationImportLogDetailView.as_view(),
        name="allocation-import-log-detail",
    ),
    path("room-requests/mine", MyRoomRequestsView.as_view(), name="room-request-mine"),
    path("room-requests", RoomRequestListCreateView.as_view(), name="room-request-list-create"),
    path(
        "room-requests/<uuid:pk>/approve",
        ApproveRoomRequestView.as_view(),
        name="room-request-approve",
    ),
    path(
        "room-requests/<uuid:pk>/reject",
        RejectRoomRequestView.as_view(),
        name="room-request-reject",
    ),
]
```

`room-requests/mine` stays listed before the bare `room-requests` path (both
are literal, non-parameterized segments — order is for readability here, not
correctness).

This changes `test_pending_list_shows_only_pending`'s (Task 2 Step 1) response
shape to a bare list `[...]`, not a paginated `{results: [...]}` — this view
is a plain `APIView`, not `ListAPIView`, so no pagination wrapper applies. The
test already handles both shapes defensively
(`items["results"] if isinstance(items, dict) and "results" in items else
items`), so no test change is needed. Likewise, `test_student_can_create_room_request`
and the other Task 1 tests continue to pass unmodified — `POST
/api/v1/hostel/room-requests` still exists at the same path with identical
behavior, now served by `RoomRequestListCreateView.post` instead of the
deleted `RoomRequestCreateView.post`.

- [ ] **Step 8: Run test to verify it passes**

Run: `../../.venv/bin/pytest hostel/tests/test_room_request_approval.py hostel/tests/test_room_requests.py -v`
Expected: all tests PASS.

- [ ] **Step 9: Run the full hostel-service test suite**

Run: `../../.venv/bin/pytest hostel/ -v`
Expected: all tests PASS.

- [ ] **Step 10: Commit**

```bash
git add services/hostel-service/hostel/services.py \
        services/hostel-service/hostel/lookups.py \
        services/hostel-service/hostel/serializers.py \
        services/hostel-service/hostel/views.py \
        services/hostel-service/hostel/urls.py \
        services/hostel-service/hostel/tests/test_room_request_approval.py
git commit -m "feat(hostel): warden approve/reject on room requests, fee/university passthrough"
```

---

### Task 3: finance-service — `FeeStructure` CRUD

**Files:**
- Modify: `services/finance-service/billing/models.py:20-28`
- Create: `services/finance-service/billing/migrations/0003_feestructure_unique_purpose.py`
- Modify: `services/finance-service/billing/serializers.py`
- Modify: `services/finance-service/billing/views.py`
- Modify: `services/finance-service/billing/urls.py`
- Test: Create `services/finance-service/billing/tests/test_fee_structures.py`

**Interfaces:**
- Consumes: `FeeStructure` model (existing, `models.py:20-28`).
- Produces: `GET /api/v1/finance/fee-structures` (list, any authenticated),
  `POST /api/v1/finance/fee-structures` (create, admin-only). Consumed by
  Task 5's frontend (warden picks a fee structure when approving) and read
  directly by Task 4's consumer via `FeeStructure.all_objects.get(...)`.

- [ ] **Step 1: Write the failing test**

Create `services/finance-service/billing/tests/test_fee_structures.py`:

```python
"""GET/POST /api/v1/finance/fee-structures — admin-managed lookup table,
replacing the hardcoded HOSTEL_FEE_AMOUNT constant billing/consumers.py used
before this feature (see Task 4 for the consumer-side wiring).
"""

import uuid

import jwt
import pytest
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

from billing.models import FeeStructure


def _make_token(tenant_id, role="admin"):
    claims = {"sub": str(uuid.uuid4()), "role": role, "tenant": str(tenant_id)}
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")


def _auth_client(tenant_id, role="admin"):
    client = APIClient()
    token = _make_token(tenant_id, role=role)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_admin_creates_fee_structure():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="admin")

    response = client.post(
        "/api/v1/finance/fee-structures",
        {"name": "Hostel Fee 2026", "amount": "5000.00", "purpose": "hostel"},
        format="json",
    )

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["name"] == "Hostel Fee 2026"
    assert body["amount"] == "5000.00"
    assert body["purpose"] == "hostel"

    fee = FeeStructure.all_objects.get(id=body["id"])
    assert fee.tenant_id == tenant_id


def test_duplicate_purpose_rejected():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="admin")
    client.post(
        "/api/v1/finance/fee-structures",
        {"name": "Hostel Fee A", "amount": "5000.00", "purpose": "hostel"},
        format="json",
    )

    response = client.post(
        "/api/v1/finance/fee-structures",
        {"name": "Hostel Fee B", "amount": "6000.00", "purpose": "hostel"},
        format="json",
    )

    assert response.status_code == 400


def test_non_admin_cannot_create():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/finance/fee-structures",
        {"name": "Hostel Fee", "amount": "5000.00", "purpose": "hostel"},
        format="json",
    )

    assert response.status_code == 403


def test_any_authenticated_role_can_list():
    tenant_id = uuid.uuid4()
    admin = _auth_client(tenant_id, role="admin")
    admin.post(
        "/api/v1/finance/fee-structures",
        {"name": "Hostel Fee", "amount": "5000.00", "purpose": "hostel"},
        format="json",
    )

    warden = _auth_client(tenant_id, role="warden")
    response = warden.get("/api/v1/finance/fee-structures")

    assert response.status_code == 200
    items = response.json()["data"]
    results = items["results"] if isinstance(items, dict) and "results" in items else items
    assert len(results) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/finance-service && ../../.venv/bin/pytest billing/tests/test_fee_structures.py -v`
Expected: FAIL — 404 (no route yet).

- [ ] **Step 3: Add the unique constraint on `(tenant_id, purpose)`**

Modify `services/finance-service/billing/models.py`:

```python
class FeeStructure(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    purpose = models.CharField(max_length=100)  # e.g. "hostel", "tuition"
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id", "purpose"], name="feestructure_tenant_purpose_unique"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.purpose})"
```

- [ ] **Step 4: Generate and apply the migration**

Run: `cd services/finance-service && ../../.venv/bin/python manage.py makemigrations billing`
Expected: creates a migration — rename to
`billing/migrations/0003_feestructure_unique_purpose.py` if named differently.

Run: `../../.venv/bin/python manage.py migrate billing`
Expected: applies cleanly (no existing rows violate the new constraint in a
fresh test/dev DB; if the running dev DB already has duplicate
`(tenant_id, purpose)` rows from manual testing, this step will fail loudly —
that's expected and correct, not a bug to work around).

- [ ] **Step 5: Add serializers**

In `services/finance-service/billing/serializers.py`, add:

```python
from billing.models import FeeStructure, Invoice


class FeeStructureSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeStructure
        fields = ["id", "name", "amount", "purpose", "created_at"]
        read_only_fields = fields


class FeeStructureCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeeStructure
        fields = ["name", "amount", "purpose"]
```

(Change the existing `from billing.models import Invoice` line at the top of
the file to `from billing.models import FeeStructure, Invoice` instead of
adding a second import line.)

- [ ] **Step 6: Add the view**

In `services/finance-service/billing/views.py`, add `FeeStructure` to the
existing `from billing.models import Invoice, Payment` line (becomes
`from billing.models import FeeStructure, Invoice, Payment`), add
`FeeStructureCreateSerializer`/`FeeStructureSerializer` to the existing
serializer import, and add this class after `InvoiceListCreateView` (before
`_payment_outcome`):

```python
class FeeStructureListCreateView(ListAPIView):
    """GET lists fee structures (tenant-scoped, paginated), any authenticated
    role — a warden approving a room request needs to read these to build a
    fee picker. POST creates one, admin-only.
    """

    serializer_class = FeeStructureSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [role_required("admin")()]
        return [IsAuthenticated()]

    def get_queryset(self):
        return FeeStructure.objects.all().order_by("purpose")

    def post(self, request):
        serializer = FeeStructureCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid fee structure payload.", errors=serializer.errors, status=400)

        fee_structure = serializer.save(tenant_id=request.tenant_id)
        return ok(
            FeeStructureSerializer(fee_structure).data,
            message="Fee structure created.",
            status=201,
        )
```

- [ ] **Step 7: Wire the URL**

In `services/finance-service/billing/urls.py`:

```python
from billing.views import FeeStructureListCreateView, InvoiceListCreateView, PayView, RazorpayOrderView
from django.urls import path

urlpatterns = [
    path("invoices", InvoiceListCreateView.as_view(), name="invoice-list-create"),
    path(
        "invoices/<uuid:invoice_id>/razorpay-order",
        RazorpayOrderView.as_view(),
        name="razorpay-order",
    ),
    path("pay", PayView.as_view(), name="pay"),
    path("fee-structures", FeeStructureListCreateView.as_view(), name="fee-structure-list-create"),
]
```

- [ ] **Step 8: Run test to verify it passes**

Run: `../../.venv/bin/pytest billing/tests/test_fee_structures.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 9: Run the full finance-service test suite**

Run: `../../.venv/bin/pytest billing/ -v`
Expected: all tests PASS.

- [ ] **Step 10: Commit**

```bash
git add services/finance-service/billing/models.py \
        services/finance-service/billing/migrations/ \
        services/finance-service/billing/serializers.py \
        services/finance-service/billing/views.py \
        services/finance-service/billing/urls.py \
        services/finance-service/billing/tests/test_fee_structures.py
git commit -m "feat(finance): add FeeStructure CRUD, replacing hardcoded hostel fee constant"
```

---

### Task 4: finance-service — consumer reads `fee_structure_id`/`university_name`, `Invoice.university_name`

**Files:**
- Modify: `services/finance-service/billing/models.py` (`Invoice`)
- Create: `services/finance-service/billing/migrations/0004_invoice_university_name.py`
- Modify: `services/finance-service/billing/consumers.py`
- Test: Modify `services/finance-service/billing/tests/test_consumers.py` (or
  create it if it doesn't exist — check first with
  `ls services/finance-service/billing/tests/`)

**Interfaces:**
- Consumes: `fee_structure_id`/`university_name` keys on the
  `hostel.allocation.requested` event payload (Task 2).
  `FeeStructure` model (Task 3).
- Produces: `Invoice.university_name` (CharField, blank-default). Consumed by
  Task 6 (Receipt PDF rendering reads `invoice.university_name`).

- [ ] **Step 1: Check for an existing consumer test file**

Run: `ls services/finance-service/billing/tests/`
If `test_consumers.py` exists, read it fully before writing Step 2 so the new
test matches its exact fixture/helper style. If it doesn't exist, Step 2
creates it from scratch using the `_auth_client`-free pattern below (event
consumers are called as plain functions, not via HTTP, so no JWT/client setup
is needed — only a hand-built event dict).

- [ ] **Step 2: Write the failing test**

Add to `services/finance-service/billing/tests/test_consumers.py` (create the
file with this content if it doesn't exist; if it exists, add these two test
functions and the necessary imports):

```python
"""billing.consumers.handle_allocation_requested: creates a pending hostel
Invoice reacting to hostel.allocation.requested. Covers both the legacy path
(no fee_structure_id — falls back to the hardcoded default) and the new
FeeStructure-driven path introduced alongside room-request approval.
"""

import uuid
from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db

from billing.consumers import handle_allocation_requested
from billing.models import FeeStructure, Invoice


def _event(tenant_id, **payload_overrides):
    payload = {
        "allocation_id": str(uuid.uuid4()),
        "student_id": str(uuid.uuid4()),
        "room_id": str(uuid.uuid4()),
        "fee_structure_id": None,
        "university_name": "",
    }
    payload.update(payload_overrides)
    return {"event_id": str(uuid.uuid4()), "type": "hostel.allocation.requested",
            "tenant_id": str(tenant_id), "payload": payload}


def test_uses_fee_structure_amount_and_stamps_university_name():
    tenant_id = uuid.uuid4()
    fee = FeeStructure.all_objects.create(
        tenant_id=tenant_id, name="Hostel Fee 2026", amount=Decimal("7500.00"), purpose="hostel"
    )
    event = _event(tenant_id, fee_structure_id=str(fee.id), university_name="Test University")

    handle_allocation_requested(event)

    invoice = Invoice.all_objects.get(tenant_id=tenant_id)
    assert invoice.amount == Decimal("7500.00")
    assert invoice.university_name == "Test University"


def test_falls_back_to_hardcoded_default_without_fee_structure():
    tenant_id = uuid.uuid4()
    event = _event(tenant_id)

    handle_allocation_requested(event)

    invoice = Invoice.all_objects.get(tenant_id=tenant_id)
    assert invoice.amount == Decimal("5000.00")
    assert invoice.university_name == ""


def test_missing_fee_structure_id_falls_back_gracefully():
    tenant_id = uuid.uuid4()
    nonexistent_id = str(uuid.uuid4())
    event = _event(tenant_id, fee_structure_id=nonexistent_id)

    handle_allocation_requested(event)

    invoice = Invoice.all_objects.get(tenant_id=tenant_id)
    assert invoice.amount == Decimal("5000.00")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd services/finance-service && ../../.venv/bin/pytest billing/tests/test_consumers.py -v`
Expected: FAIL — `AttributeError`/`FieldError` (`university_name` doesn't
exist on `Invoice` yet).

- [ ] **Step 4: Add `Invoice.university_name`**

Modify `services/finance-service/billing/models.py`, the `Invoice` class:

```python
class Invoice(TenantModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PAID = "paid", "Paid"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student_id = models.UUIDField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    purpose = models.CharField(max_length=100)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)
    # Denormalized from auth-service's Institution.name at invoice-creation
    # time (see billing/consumers.py: handle_allocation_requested). Consumers
    # run with no request context and no live cross-service HTTP call of
    # their own (see hostel/lookups.py: resolve_institution_name, called by
    # the WARDEN's live request in hostel-service instead, then threaded
    # through the event payload) — this field exists so Task 6's receipt PDF
    # can render a university name without finance-service ever calling
    # auth-service itself.
    university_name = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tenant_id", "status"], name="invoice_tenant_status"),
            models.Index(fields=["tenant_id", "student_id"], name="invoice_tenant_student"),
        ]

    def __str__(self):
        return f"Invoice {self.id} ({self.status})"
```

- [ ] **Step 5: Generate and apply the migration**

Run: `../../.venv/bin/python manage.py makemigrations billing`
Expected: creates a migration — rename to
`billing/migrations/0004_invoice_university_name.py` if named differently.

Run: `../../.venv/bin/python manage.py migrate billing`

- [ ] **Step 6: Update the consumer to read fee_structure_id/university_name**

Modify `services/finance-service/billing/consumers.py`:

```python
"""Event consumers (Task 4.5) — the saga step that reacts to hostel allocation.

... (existing docstring lines 1-40 unchanged) ...
"""

from decimal import Decimal

from billing.models import FeeStructure, Invoice
from django.db import transaction
from suerp_common.inbox import idempotent
from suerp_common.outbox import publish_event

HOSTEL_FEE_AMOUNT = Decimal("5000.00")


def _resolve_hostel_fee_amount(tenant_id, fee_structure_id) -> Decimal:
    """Look up the warden-chosen FeeStructure's amount, falling back to the
    hardcoded default when no fee_structure_id was passed (legacy direct-
    allocate path — AllocateView/AllocateBulkView don't collect a fee choice
    at all) or when the id doesn't resolve (deleted/cross-tenant/typo'd —
    fail open to the old default rather than blocking invoice creation
    entirely, since this consumer has no way to surface an error back to the
    warden who already approved the request).
    """
    if not fee_structure_id:
        return HOSTEL_FEE_AMOUNT

    fee_structure = FeeStructure.all_objects.filter(
        tenant_id=tenant_id, id=fee_structure_id
    ).first()
    return fee_structure.amount if fee_structure is not None else HOSTEL_FEE_AMOUNT


@idempotent
def handle_allocation_requested(event: dict) -> None:
    """Handle ``hostel.allocation.requested``: create a pending hostel Invoice.

    Expects ``event["payload"]`` to contain ``allocation_id``, ``student_id``,
    ``room_id``, and (new) ``fee_structure_id``/``university_name`` — both
    optional, present only when the allocation came from warden room-request
    approval rather than the direct AllocateView/AllocateBulkView path.
    """
    tenant_id = event["tenant_id"]
    payload = event["payload"]
    student_id = payload["student_id"]
    allocation_id = payload["allocation_id"]
    fee_structure_id = payload.get("fee_structure_id")
    university_name = payload.get("university_name") or ""

    amount = _resolve_hostel_fee_amount(tenant_id, fee_structure_id)

    with transaction.atomic():
        invoice = Invoice.all_objects.create(
            tenant_id=tenant_id,
            student_id=student_id,
            amount=amount,
            purpose="hostel",
            status=Invoice.Status.PENDING,
            university_name=university_name,
        )

        publish_event(
            "finance.invoice.created",
            tenant_id=tenant_id,
            payload={
                "invoice_id": str(invoice.id),
                "student_id": student_id,
                "allocation_id": allocation_id,
                "amount": str(amount),
                "purpose": "hostel",
            },
        )
```

- [ ] **Step 7: Run test to verify it passes**

Run: `../../.venv/bin/pytest billing/tests/test_consumers.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 8: Run the full finance-service test suite**

Run: `../../.venv/bin/pytest billing/ -v`
Expected: all tests PASS (confirms the existing
`handle_allocation_requested` behavior for events with no
`fee_structure_id` key at all — e.g. any pre-existing test fixture event
dicts without the new keys — still works via `.get(...)`'s `None` default).

- [ ] **Step 9: Commit**

```bash
git add services/finance-service/billing/models.py \
        services/finance-service/billing/migrations/ \
        services/finance-service/billing/consumers.py \
        services/finance-service/billing/tests/test_consumers.py
git commit -m "feat(finance): consumer prices invoice from FeeStructure, stamps university_name"
```

---

### Task 5: finance-service — Receipt PDF/QR/HMAC generation on payment success

**Files:**
- Modify: `services/finance-service/requirements.txt`
- Modify: `services/finance-service/billing/models.py` (`Receipt`)
- Create: `services/finance-service/billing/migrations/0005_receipt_verification_fields.py`
- Create: `services/finance-service/billing/receipts.py`
- Modify: `services/finance-service/billing/views.py` (`PayView`)
- Modify: `services/finance-service/billing/serializers.py`
- Modify: `services/finance-service/billing/urls.py`
- Modify: `services/finance-service/config/settings.py`
- Test: Create `services/finance-service/billing/tests/test_receipts.py`

**Interfaces:**
- Consumes: `Invoice.university_name` (Task 4), `Payment` (existing).
- Produces: `billing/receipts.py: generate_receipt(payment: Payment) ->
  Receipt` (called from `PayView`). `Receipt.pdf_data` (BinaryField),
  `Receipt.verification_token` (CharField, the HMAC-signed opaque token),
  `Receipt.verify_url` (CharField, the full frontend URL embedded in the QR).
  `GET /api/v1/finance/receipts/<uuid:receipt_id>/pdf` (download),
  `POST /api/v1/finance/receipts/verify` (verify a token, returns receipt
  details). Consumed by Task 6 (frontend verify page + student download
  button).

- [ ] **Step 1: Add new dependencies**

Modify `services/finance-service/requirements.txt`, adding after `razorpay`:

```
razorpay
reportlab
qrcode[pil]
-e ../../shared/libs/suerp_common
```

Run: `cd services/finance-service && ../../.venv/bin/pip install -r requirements.txt`
Expected: installs `reportlab`, `qrcode`, and `Pillow` (qrcode's `[pil]` extra)
without errors.

- [ ] **Step 2: Add `RECEIPT_HMAC_SECRET` and `FRONTEND_URL` settings**

Modify `services/finance-service/config/settings.py`, adding near the existing
`JWT_SIGNING_KEY` line:

```python
JWT_SIGNING_KEY = env("JWT_SIGNING_KEY", default="dev-insecure-change-me")
RECEIPT_HMAC_SECRET = env("RECEIPT_HMAC_SECRET", default="dev-insecure-receipt-secret")
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:3001")
```

`RECEIPT_HMAC_SECRET` is deliberately separate from `JWT_SIGNING_KEY` — a
leaked or rotated JWT key shouldn't invalidate every previously-issued
receipt's verification token. `FRONTEND_URL` is the base URL embedded in the
QR code's verify link (distinct from the existing `GATEWAY_URL`, which points
at the API gateway, not the Next.js frontend).

Also add `RECEIPT_HMAC_SECRET=dev-insecure-receipt-secret` and
`FRONTEND_URL=http://localhost:3001` to
`infra/docker-compose.yml`'s `finance-service` (and `finance-consumer`, if it
shares the same `environment: &finance-env` YAML anchor — check the anchor
name in that file first) environment block, matching how `JWT_SIGNING_KEY` is
already set there.

- [ ] **Step 3: Write the failing test**

Create `services/finance-service/billing/tests/test_receipts.py`:

```python
"""billing.receipts.generate_receipt: renders a PDF receipt (reportlab) with
an embedded QR code (qrcode) linking to a verify page, and an HMAC-signed
verification_token (separate RECEIPT_HMAC_SECRET, not JWT_SIGNING_KEY) that
POST /api/v1/finance/receipts/verify checks against tamper.

Also covers PayView's synchronous hook: a successful /pay call creates a
Receipt in the same request, and its PDF/verify endpoints work end to end.
"""

import uuid
from decimal import Decimal

import jwt
import pytest
from django.conf import settings
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

from billing.models import Invoice, Payment, Receipt
from billing.receipts import generate_receipt, verify_token


def _make_token(tenant_id, role="student", user_id=None):
    claims = {"sub": str(user_id or uuid.uuid4()), "role": role, "tenant": str(tenant_id)}
    return jwt.encode(claims, settings.JWT_SIGNING_KEY, algorithm="HS256")


def _auth_client(tenant_id, **kwargs):
    client = APIClient()
    token = _make_token(tenant_id, **kwargs)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def _make_paid_invoice_and_payment(tenant_id, student_id):
    invoice = Invoice.all_objects.create(
        tenant_id=tenant_id,
        student_id=student_id,
        amount=Decimal("5000.00"),
        purpose="hostel",
        status=Invoice.Status.PAID,
        university_name="Test University",
    )
    payment = Payment.all_objects.create(
        tenant_id=tenant_id,
        invoice=invoice,
        amount=Decimal("5000.00"),
        status=Payment.Status.SUCCESS,
        gateway_ref="sim-123",
    )
    return invoice, payment


def test_generate_receipt_produces_pdf_bytes_and_verifiable_token():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice, payment = _make_paid_invoice_and_payment(tenant_id, student_id)

    receipt = generate_receipt(payment)

    assert receipt.pdf_data.startswith(b"%PDF")
    assert receipt.verification_token
    assert receipt.verify_url.endswith(f"/verify-receipt?token={receipt.verification_token}")
    assert verify_token(receipt.verification_token) == receipt.id


def test_verify_token_rejects_tampered_token():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice, payment = _make_paid_invoice_and_payment(tenant_id, student_id)
    receipt = generate_receipt(payment)

    tampered = receipt.verification_token[:-1] + ("a" if receipt.verification_token[-1] != "a" else "b")

    assert verify_token(tampered) is None


def test_pay_creates_receipt_synchronously():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice = Invoice.all_objects.create(
        tenant_id=tenant_id,
        student_id=student_id,
        amount=Decimal("100.00"),
        purpose="hostel",
        status=Invoice.Status.PENDING,
        university_name="Test University",
    )
    client = _auth_client(tenant_id, role="student", user_id=student_id)

    response = client.post(
        "/api/v1/finance/pay",
        {"invoice_id": str(invoice.id), "idempotency_key": "idem-1"},
        format="json",
    )

    assert response.status_code == 200, response.content
    payment_id = response.json()["data"]["payment_id"]
    receipt = Receipt.all_objects.get(payment_id=payment_id)
    assert receipt.pdf_data.startswith(b"%PDF")


def test_download_receipt_pdf():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice, payment = _make_paid_invoice_and_payment(tenant_id, student_id)
    receipt = generate_receipt(payment)

    client = _auth_client(tenant_id, role="student", user_id=student_id)
    response = client.get(f"/api/v1/finance/receipts/{receipt.id}/pdf")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_verify_endpoint_valid_token():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice, payment = _make_paid_invoice_and_payment(tenant_id, student_id)
    receipt = generate_receipt(payment)

    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.post(
        "/api/v1/finance/receipts/verify", {"token": receipt.verification_token}, format="json"
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["valid"] is True
    assert body["receipt_no"] == receipt.receipt_no
    assert body["amount"] == "5000.00"


def test_verify_endpoint_invalid_token():
    tenant_id = uuid.uuid4()
    warden_client = _auth_client(tenant_id, role="warden")
    response = warden_client.post(
        "/api/v1/finance/receipts/verify", {"token": "not-a-real-token"}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["data"]["valid"] is False


def test_student_role_forbidden_from_verify():
    tenant_id = uuid.uuid4()
    student_client = _auth_client(tenant_id, role="student")
    response = student_client.post(
        "/api/v1/finance/receipts/verify", {"token": "whatever"}, format="json"
    )

    assert response.status_code == 403
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd services/finance-service && ../../.venv/bin/pytest billing/tests/test_receipts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'billing.receipts'`.

- [ ] **Step 5: Add `Receipt` fields**

Modify `services/finance-service/billing/models.py`, the `Receipt` class:

```python
class Receipt(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name="receipt")
    receipt_no = models.CharField(max_length=100)
    # Rendered once at payment-success time (see billing/receipts.py:
    # generate_receipt, called synchronously from PayView) and served as-is
    # on every download — no re-rendering, no drift between what the QR/HMAC
    # attest to and what's actually in the PDF bytes.
    pdf_data = models.BinaryField()
    # HMAC-SHA256(receipt_id, RECEIPT_HMAC_SECRET) hex digest — see
    # billing/receipts.py: sign_token/verify_token. Opaque; carries no
    # embedded data of its own (unlike a JWT), so a leaked token reveals
    # nothing beyond "this is receipt X" once looked up.
    verification_token = models.CharField(max_length=64)
    # Full frontend URL embedded in the QR code, e.g.
    # "http://localhost:3001/verify-receipt?token=<verification_token>".
    verify_url = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.receipt_no
```

(`pdf_url` is removed — it was always unpopulated dead code, per the research
that scoped this plan; `pdf_data` replaces it with the actual bytes.)

- [ ] **Step 6: Generate and apply the migration**

Run: `../../.venv/bin/python manage.py makemigrations billing`
Expected: creates a migration — rename to
`billing/migrations/0005_receipt_verification_fields.py` if named
differently. Since `pdf_data`/`verification_token`/`verify_url` have no
`default=` and the table may already have rows from Task 3/4 testing in a
long-lived dev DB (not in a fresh CI run), Django will prompt for a one-off
default when generating the migration interactively — if running
non-interactively, add explicit defaults so `makemigrations` doesn't block:
add `default=b""` to `pdf_data` and `default=""` to `verification_token`/
`verify_url` in the model temporarily is unnecessary for a fresh test
database (which this plan's automated test runs always use), but if
`makemigrations` errors asking for a default in your local shell, answer `1`
(provide a one-off default) with `b""` for `pdf_data` and `""` for the two
CharFields — existing `Receipt` rows are a non-issue in practice since
`Receipt` has never been created anywhere in this codebase until this task.

Run: `../../.venv/bin/python manage.py migrate billing`

- [ ] **Step 7: Write `billing/receipts.py`**

Create `services/finance-service/billing/receipts.py`:

```python
"""Payment receipt generation: PDF (reportlab) + embedded QR (qrcode) linking
to a verify page, plus an HMAC-signed verification_token.

Called synchronously from billing.views.PayView inside its existing
transaction.atomic() block on payment success — see that module's docstring
for why this stays synchronous rather than becoming a new event-consumer
path (no request context available there to resolve a URL correctly, and no
precedent in this codebase for a service consuming its own published event).

HMAC choice: RECEIPT_HMAC_SECRET (config.settings) is a signing secret
distinct from JWT_SIGNING_KEY (shared inter-service auth secret) so that
rotating one never invalidates the other. The token itself carries no
embedded data (unlike a JWT) — it's HMAC-SHA256(receipt_id_bytes, secret)
hex-encoded, opaque, and verify_token() below re-derives the same digest for
a receipt_id looked up from the DB and compares with hmac.compare_digest
(constant-time, avoiding timing side-channels on the comparison itself).
"""

import hashlib
import hmac
import io
import uuid

import qrcode
from django.conf import settings
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def _sign(receipt_id: uuid.UUID) -> str:
    return hmac.new(
        settings.RECEIPT_HMAC_SECRET.encode(), str(receipt_id).encode(), hashlib.sha256
    ).hexdigest()


def verify_token(token: str) -> uuid.UUID | None:
    """Return the receipt_id this token was issued for, or None if the token
    doesn't match any receipt. Callers look up the Receipt by scanning is not
    feasible (the token doesn't embed the id) — see billing.views.VerifyReceiptView,
    which instead accepts the token, and this function is used the OTHER
    direction: given a receipt_id candidate, does the stored token match?
    Kept here as the single source of truth for "does this token match this
    receipt_id" so PDF generation and verification never drift.
    """
    from billing.models import Receipt

    receipt = Receipt.all_objects.filter(verification_token=token).first()
    if receipt is None:
        return None
    expected = _sign(receipt.id)
    if not hmac.compare_digest(expected, token):
        return None
    return receipt.id


def _render_pdf(payment, receipt_id: uuid.UUID, receipt_no: str, verify_url: str) -> bytes:
    invoice = payment.invoice
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    pdf.setFont("Helvetica-Bold", 16)
    university_name = invoice.university_name or "SU-ERP"
    pdf.drawCentredString(width / 2, height - 30 * mm, university_name)

    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawCentredString(width / 2, height - 40 * mm, "Payment Receipt")

    pdf.setFont("Helvetica", 11)
    lines = [
        f"Receipt No: {receipt_no}",
        f"Purpose: {invoice.purpose}",
        f"Amount: {invoice.amount}",
        f"Status: {payment.status}",
        f"Gateway Reference: {payment.gateway_ref}",
        f"Paid On: {payment.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    y = height - 55 * mm
    for line in lines:
        pdf.drawString(25 * mm, y, line)
        y -= 8 * mm

    qr_image = qrcode.make(verify_url)
    qr_buffer = io.BytesIO()
    qr_image.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    from reportlab.lib.utils import ImageReader

    pdf.drawImage(ImageReader(qr_buffer), 25 * mm, y - 45 * mm, width=35 * mm, height=35 * mm)

    pdf.setFont("Helvetica", 8)
    pdf.drawString(25 * mm, y - 50 * mm, f"Verify: {verify_url}")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def generate_receipt(payment) -> "Receipt":
    """Create and return a Receipt for a successful Payment, rendering the
    PDF (with embedded QR + HMAC token) once and storing the bytes. Caller
    (billing.views.PayView) must already hold a transaction.atomic() block —
    this performs a single Receipt.objects.create() and no I/O beyond
    in-memory PDF/QR rendering, so it's safe to call inline.
    """
    from billing.models import Receipt

    receipt_id = uuid.uuid4()
    receipt_no = f"RCPT-{receipt_id.hex[:12].upper()}"
    token = _sign(receipt_id)
    verify_url = f"{settings.FRONTEND_URL}/verify-receipt?token={token}"

    pdf_bytes = _render_pdf(payment, receipt_id, receipt_no, verify_url)

    return Receipt.objects.create(
        id=receipt_id,
        tenant_id=payment.tenant_id,
        payment=payment,
        receipt_no=receipt_no,
        pdf_data=pdf_bytes,
        verification_token=token,
        verify_url=verify_url,
    )
```

- [ ] **Step 8: Hook `generate_receipt` into `PayView`**

Modify `services/finance-service/billing/views.py`: add
`from billing.receipts import generate_receipt` to the imports, and call it
right after the existing `Payment.objects.create(...)` success branch
(currently lines 152-159), before the `invoice.status = Invoice.Status.PAID`
assignment — reordered slightly so `generate_receipt` (which reads
`payment.invoice` and `payment.created_at`) runs against a fully-formed
`Payment` row:

```python
            if result.success:
                payment = Payment.objects.create(
                    tenant_id=invoice.tenant_id,
                    invoice=invoice,
                    amount=invoice.amount,
                    status=Payment.Status.SUCCESS,
                    gateway_ref=result.gateway_ref,
                    idempotency_key=idempotency_key,
                )
                invoice.status = Invoice.Status.PAID
                invoice.idempotency_key = idempotency_key
                invoice.save(update_fields=["status", "idempotency_key"])
                generate_receipt(payment)

                publish_event(
                    "finance.payment.success",
                    tenant_id=str(invoice.tenant_id),
                    payload={
                        "invoice_id": str(invoice.id),
                        "student_id": str(invoice.student_id),
                        "purpose": invoice.purpose,
                        "amount": str(invoice.amount),
                    },
                )
```

(Only the `generate_receipt(payment)` line is new — every other line in this
block is unchanged from the existing file, shown here for exact placement
context.)

- [ ] **Step 9: Add the PDF-download and verify views**

In `services/finance-service/billing/views.py`, add these two classes after
`PayView` (at the end of the file):

```python
class ReceiptPdfView(APIView):
    """GET /api/v1/finance/receipts/<uuid:receipt_id>/pdf — download the
    stored PDF bytes as-is (rendered once at payment-success time, see
    billing.receipts.generate_receipt). Tenant-scoped: cross-tenant/unknown
    receipt_id -> 404, same pattern as RazorpayOrderView.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, receipt_id):
        from django.http import HttpResponse

        receipt = get_object_or_404(Receipt.objects, id=receipt_id)
        response = HttpResponse(bytes(receipt.pdf_data), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{receipt.receipt_no}.pdf"'
        return response


class VerifyReceiptView(APIView):
    """POST /api/v1/finance/receipts/verify — warden/admin checks a
    verification_token (scanned from the QR or typed from the plain-text
    code beneath it). Returns {valid, receipt_no, amount, purpose,
    university_name, paid_on} on a match, {valid: false} otherwise — never
    404s on a bad token, since "this token is invalid" is itself a normal,
    expected verification outcome, not an error.
    """

    permission_classes = [role_required("warden", "admin")]

    def post(self, request):
        token = request.data.get("token", "")
        receipt_id = verify_token(token)
        if receipt_id is None:
            return ok({"valid": False})

        receipt = Receipt.objects.get(id=receipt_id)
        invoice = receipt.payment.invoice
        return ok(
            {
                "valid": True,
                "receipt_no": receipt.receipt_no,
                "amount": str(invoice.amount),
                "purpose": invoice.purpose,
                "university_name": invoice.university_name,
                "paid_on": receipt.created_at.isoformat(),
            }
        )
```

Add `Receipt` to the existing `from billing.models import FeeStructure,
Invoice, Payment` line (becomes `from billing.models import FeeStructure,
Invoice, Payment, Receipt`), and add
`from billing.receipts import generate_receipt, verify_token` (combining with
Step 8's import into one line).

- [ ] **Step 10: Wire the URLs**

In `services/finance-service/billing/urls.py`:

```python
from billing.views import (
    FeeStructureListCreateView,
    InvoiceListCreateView,
    PayView,
    RazorpayOrderView,
    ReceiptPdfView,
    VerifyReceiptView,
)
from django.urls import path

urlpatterns = [
    path("invoices", InvoiceListCreateView.as_view(), name="invoice-list-create"),
    path(
        "invoices/<uuid:invoice_id>/razorpay-order",
        RazorpayOrderView.as_view(),
        name="razorpay-order",
    ),
    path("pay", PayView.as_view(), name="pay"),
    path("fee-structures", FeeStructureListCreateView.as_view(), name="fee-structure-list-create"),
    path("receipts/verify", VerifyReceiptView.as_view(), name="receipt-verify"),
    path("receipts/<uuid:receipt_id>/pdf", ReceiptPdfView.as_view(), name="receipt-pdf"),
]
```

Note `receipts/verify` is registered **before**
`receipts/<uuid:receipt_id>/pdf` — Django tries `path()` patterns in list
order and `verify` is a literal segment that would otherwise risk (depending
on Django version internals) being tried against the `<uuid:receipt_id>`
converter first; listing the non-parameterized literal route first avoids
any ambiguity.

- [ ] **Step 11: Run test to verify it passes**

Run: `../../.venv/bin/pytest billing/tests/test_receipts.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 12: Run the full finance-service test suite**

Run: `../../.venv/bin/pytest billing/ -v`
Expected: all tests PASS.

- [ ] **Step 13: Commit**

```bash
git add services/finance-service/requirements.txt \
        services/finance-service/config/settings.py \
        services/finance-service/billing/models.py \
        services/finance-service/billing/migrations/ \
        services/finance-service/billing/receipts.py \
        services/finance-service/billing/views.py \
        services/finance-service/billing/serializers.py \
        services/finance-service/billing/urls.py \
        services/finance-service/billing/tests/test_receipts.py \
        infra/docker-compose.yml
git commit -m "feat(finance): generate signed PDF receipt with QR on payment success"
```

---

### Task 6: Frontend — student room-request UI, warden approval queue + fee picker, receipt download, verify page

**Files:**
- Modify: `frontend/su-erp-web/src/app/(dashboard)/student/page.tsx`
- Modify: `frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx`
- Create: `frontend/su-erp-web/src/app/verify-receipt/page.tsx`
- Modify: `frontend/su-erp-web/src/lib/api.ts` (if a new helper is needed —
  check first; `api.download` from the prior plan already covers PDF
  download, no new helper needed there)

**Interfaces:**
- Consumes: `POST /api/v1/hostel/room-requests`,
  `GET /api/v1/hostel/room-requests/mine`,
  `GET /api/v1/hostel/room-requests?status=pending`,
  `POST /api/v1/hostel/room-requests/<id>/approve`,
  `POST /api/v1/hostel/room-requests/<id>/reject`,
  `GET /api/v1/finance/fee-structures`,
  `GET /api/v1/finance/receipts/<id>/pdf` (via `api.download`, already built
  in the prior plan), `POST /api/v1/finance/receipts/verify` (all Tasks 1-5).

- [ ] **Step 1: Read the current student page's fees/invoices panel for its exact patterns**

Run: `grep -n "Fees & invoices\|isPaid\|StatusPill" "frontend/su-erp-web/src/app/(dashboard)/student/page.tsx"`

Note the existing invoice table's row shape (columns Purpose/Amount/
Status/Action) — the new "Download receipt" button goes in that same Action
column, alongside the existing Pay button, shown only when `isPaid(status)`
is true.

- [ ] **Step 2: Add "Request a room" panel and "My requests" list to the student page**

In `frontend/su-erp-web/src/app/(dashboard)/student/page.tsx`, add a new
component (place it near the existing fees/invoices panel component, follow
that component's exact structural style — `Card`/`CardHeader`/`CardBody`,
`useState`/`useEffect`/`useCallback`, `errMsg`/`Alert`/`DataPanel` imports
already present at the top of the file):

```tsx
interface AvailableRoom {
  id: string;
  block_name: string;
  room_no: string;
  is_available: boolean;
}

interface RoomRequest {
  id: string;
  room_id: string;
  room_name: string;
  status: string;
  requested_on: string;
  rejection_reason: string;
}

function RoomRequestPanel() {
  const [rooms, setRooms] = useState<AvailableRoom[]>([]);
  const [myRequests, setMyRequests] = useState<RoomRequest[]>([]);
  const [selectedRoomId, setSelectedRoomId] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [roomsData, requestsData] = await Promise.all([
        api.get("/api/v1/hostel/rooms/available"),
        api.get("/api/v1/hostel/room-requests/mine"),
      ]);
      setRooms(listItems<AvailableRoom>(roomsData));
      setMyRequests(listItems<RoomRequest>(requestsData));
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedRoomId) return;
    setPending(true);
    setError(null);
    try {
      await api.post("/api/v1/hostel/room-requests", { room_id: selectedRoomId });
      setSelectedRoomId("");
      await load();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Request a room" />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <Field label="Room" htmlFor="room-select">
            <select
              id="room-select"
              value={selectedRoomId}
              onChange={(e) => setSelectedRoomId(e.target.value)}
              className="block w-full rounded border border-line bg-surface px-3 py-2 text-sm text-ink"
            >
              <option value="">Select a room…</option>
              {rooms.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.block_name} - {r.room_no}
                </option>
              ))}
            </select>
          </Field>
          {error && <Alert tone="error">{error}</Alert>}
          <Button type="submit" loading={pending} disabled={!selectedRoomId}>
            Request
          </Button>
        </form>

        <div className="mt-6">
          <DataPanel
            title="My requests"
            loading={loading}
            error={null}
            isEmpty={myRequests.length === 0}
            emptyLabel="No room requests yet."
          >
            <Table>
              <THead>
                <HeaderRow>
                  <TH>Room</TH>
                  <TH>Requested</TH>
                  <TH>Status</TH>
                  <TH>Note</TH>
                </HeaderRow>
              </THead>
              <TBody>
                {myRequests.map((r) => (
                  <Row key={r.id}>
                    <TD className="font-medium">{r.room_name}</TD>
                    <TD className="text-muted">{new Date(r.requested_on).toLocaleString()}</TD>
                    <TD>
                      <StatusPill status={r.status} />
                    </TD>
                    <TD className="text-muted">{r.rejection_reason}</TD>
                  </Row>
                ))}
              </TBody>
            </Table>
          </DataPanel>
        </div>
      </CardBody>
    </Card>
  );
}
```

Add `<RoomRequestPanel />` to the student page's main render output, near
where the fees/invoices panel is rendered. `RoomSerializer` (from
`hostel/serializers.py`, already existing) provides `block_name`/`room_no` on
`/api/v1/hostel/rooms/available` — no backend change needed for this step.

- [ ] **Step 3: Add "Download receipt" button to the student's invoice table**

In the same file, find the existing invoice row rendering (the Action column
with the Pay/Paid button) and add a receipt download button next to it, shown
only when the invoice is paid:

```tsx
{isPaid(invoice.status) && (
  <Button
    variant="ghost"
    size="sm"
    onClick={() => api.download(`/api/v1/finance/receipts/by-invoice/${invoice.id}/pdf`, `receipt-${invoice.id}.pdf`)}
  >
    Download receipt
  </Button>
)}
```

This references a `receipts/by-invoice/<invoice_id>/pdf` route that doesn't
exist yet in Task 5 (which only added `receipts/<receipt_id>/pdf`, keyed by
receipt id, not invoice id — the student page only has the `invoice`, not the
`receipt.id`, since `Invoice`/`Receipt` aren't joined in any endpoint the
student page currently calls). **Add this endpoint now**, back in
`services/finance-service/billing/views.py` (append to the file, after
`ReceiptPdfView`):

```python
class ReceiptPdfByInvoiceView(APIView):
    """GET /api/v1/finance/receipts/by-invoice/<uuid:invoice_id>/pdf —
    convenience lookup for the student invoice table, which only has an
    invoice_id on hand (Invoice and Receipt aren't joined in any response
    the student page already fetches). 404s if the invoice has no receipt
    yet (unpaid, or paid before this feature existed).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, invoice_id):
        from django.http import HttpResponse

        receipt = get_object_or_404(Receipt.objects, payment__invoice_id=invoice_id)
        response = HttpResponse(bytes(receipt.pdf_data), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{receipt.receipt_no}.pdf"'
        return response
```

And in `services/finance-service/billing/urls.py`, add before the
`receipts/<uuid:receipt_id>/pdf` line (literal-segment-before-converter
ordering, same reasoning as `receipts/verify`):

```python
    path(
        "receipts/by-invoice/<uuid:invoice_id>/pdf",
        ReceiptPdfByInvoiceView.as_view(),
        name="receipt-pdf-by-invoice",
    ),
```

And import `ReceiptPdfByInvoiceView` alongside the other view imports in that
file.

Write a matching backend test in
`services/finance-service/billing/tests/test_receipts.py` (add to the
existing file from Task 5):

```python
def test_download_receipt_pdf_by_invoice_id():
    tenant_id = uuid.uuid4()
    student_id = uuid.uuid4()
    invoice, payment = _make_paid_invoice_and_payment(tenant_id, student_id)
    generate_receipt(payment)

    client = _auth_client(tenant_id, role="student", user_id=student_id)
    response = client.get(f"/api/v1/finance/receipts/by-invoice/{invoice.id}/pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
```

Run: `cd services/finance-service && ../../.venv/bin/pytest billing/tests/test_receipts.py -v`
Expected: all 8 tests PASS (7 from Task 5 + this one).

- [ ] **Step 4: Add the warden approval queue with fee-structure picker**

In `frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx`, add a new
component (mirroring `ImportLogs`'s `DataPanel`/`useCallback`/`useEffect`
structure) after the existing components:

```tsx
interface FeeStructure {
  id: string;
  name: string;
  amount: string;
  purpose: string;
}

interface PendingRequest {
  id: string;
  student_id: string;
  room_id: string;
  room_name: string;
  status: string;
  requested_on: string;
}

function RoomRequestQueue() {
  const [requests, setRequests] = useState<PendingRequest[]>([]);
  const [feeStructures, setFeeStructures] = useState<FeeStructure[]>([]);
  const [selectedFee, setSelectedFee] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [requestsData, feesData] = await Promise.all([
        api.get("/api/v1/hostel/room-requests?status=pending"),
        api.get("/api/v1/finance/fee-structures"),
      ]);
      setRequests(listItems<PendingRequest>(requestsData));
      setFeeStructures(listItems<FeeStructure>(feesData));
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function approve(id: string) {
    const feeStructureId = selectedFee[id];
    if (!feeStructureId) {
      setActionError("Pick a fee structure before approving.");
      return;
    }
    setActionError(null);
    try {
      await api.post(`/api/v1/hostel/room-requests/${id}/approve`, {
        fee_structure_id: feeStructureId,
      });
      await load();
    } catch (err) {
      setActionError(errMsg(err));
    }
  }

  async function reject(id: string) {
    setActionError(null);
    try {
      await api.post(`/api/v1/hostel/room-requests/${id}/reject`, {});
      await load();
    } catch (err) {
      setActionError(errMsg(err));
    }
  }

  return (
    <DataPanel
      title="Pending room requests"
      loading={loading}
      error={error}
      isEmpty={requests.length === 0}
      emptyLabel="No pending room requests."
    >
      {actionError && <Alert tone="error">{actionError}</Alert>}
      <Table>
        <THead>
          <HeaderRow>
            <TH>Room</TH>
            <TH>Requested</TH>
            <TH>Fee</TH>
            <TH />
          </HeaderRow>
        </THead>
        <TBody>
          {requests.map((r) => (
            <Row key={r.id}>
              <TD className="font-medium">{r.room_name}</TD>
              <TD className="text-muted">{new Date(r.requested_on).toLocaleString()}</TD>
              <TD>
                <select
                  value={selectedFee[r.id] ?? ""}
                  onChange={(e) => setSelectedFee((prev) => ({ ...prev, [r.id]: e.target.value }))}
                  className="rounded border border-line bg-surface px-2 py-1 text-sm text-ink"
                >
                  <option value="">Select fee…</option>
                  {feeStructures.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name} ({f.amount})
                    </option>
                  ))}
                </select>
              </TD>
              <TD className="space-x-2">
                <Button size="sm" onClick={() => approve(r.id)}>
                  Approve
                </Button>
                <Button size="sm" variant="ghost" onClick={() => reject(r.id)}>
                  Reject
                </Button>
              </TD>
            </Row>
          ))}
        </TBody>
      </Table>
    </DataPanel>
  );
}
```

Add `<RoomRequestQueue />` to the warden page's main render output.

- [ ] **Step 5: Create the verify-receipt frontend page**

Create `frontend/su-erp-web/src/app/verify-receipt/page.tsx`. First check
`frontend/su-erp-web/src/app/(dashboard)/` for the layout wrapper pattern
(auth guard) other dashboard pages use, and check whether a `useSearchParams`
pattern already exists elsewhere in the app (`grep -rn "useSearchParams"
frontend/su-erp-web/src`) to match its exact style before writing this file.
Since the page must require warden/admin login (per the earlier design
decision), place it under `(dashboard)` alongside `warden/page.tsx`, at
`frontend/su-erp-web/src/app/(dashboard)/verify-receipt/page.tsx` instead of
top-level `src/app/verify-receipt/page.tsx`, so it inherits the same
dashboard auth-guard layout every other role-gated page uses — check
`frontend/su-erp-web/src/app/(dashboard)/layout.tsx` first to confirm it does
enforce login for all its children before relying on that.

```tsx
"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { errMsg } from "@/lib/errors";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { Alert } from "@/components/ui/Alert";

interface VerifyResult {
  valid: boolean;
  receipt_no?: string;
  amount?: string;
  purpose?: string;
  university_name?: string;
  paid_on?: string;
}

export default function VerifyReceiptPage() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [result, setResult] = useState<VerifyResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) {
      setError("No verification token provided.");
      setLoading(false);
      return;
    }
    api
      .post<VerifyResult>("/api/v1/finance/receipts/verify", { token })
      .then(setResult)
      .catch((err) => setError(errMsg(err)))
      .finally(() => setLoading(false));
  }, [token]);

  return (
    <div className="mx-auto max-w-md p-6">
      <Card>
        <CardHeader title="Receipt verification" />
        <CardBody>
          {loading && <p className="text-[13px] text-muted">Verifying…</p>}
          {error && <Alert tone="error">{error}</Alert>}
          {result && !result.valid && <Alert tone="error">Invalid or unrecognized receipt.</Alert>}
          {result && result.valid && (
            <div className="space-y-2 text-sm">
              <Alert tone="success">Valid receipt.</Alert>
              <p><span className="text-muted">Receipt No:</span> {result.receipt_no}</p>
              <p><span className="text-muted">University:</span> {result.university_name}</p>
              <p><span className="text-muted">Purpose:</span> {result.purpose}</p>
              <p><span className="text-muted">Amount:</span> {result.amount}</p>
              <p><span className="text-muted">Paid On:</span> {result.paid_on && new Date(result.paid_on).toLocaleString()}</p>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
```

Adjust the actual `Card`/`Alert` import paths to match whatever
`warden/page.tsx` already imports at its top (check its import block first
and copy the exact paths — don't guess the component library's file
locations).

- [ ] **Step 6: Run frontend lint and build**

Run: `cd frontend/su-erp-web && npm run lint && npm run build`
Expected: no errors. Fix any type mismatches against the actual `Card`/
`Button`/`DataPanel`/`Table` component prop signatures found in Step 5's
import-path check.

- [ ] **Step 7: Manually verify in the browser**

Rebuild and restart the `frontend`, `finance-service`, `finance-consumer`,
`hostel-service`, `hostel-consumer` containers (same rebuild-then-`up -d`
sequence used in the prior plan's Task 3 Step 5), apply migrations inside
each container (`docker compose exec finance-service python manage.py
migrate billing`, `docker compose exec hostel-service python manage.py
migrate hostel`).

Log in as a student: submit a room request from the new panel, confirm it
shows "pending" in "My requests". Log in as a warden: see the request in
"Pending room requests", create a fee structure first if none exist yet (via
`POST /api/v1/finance/fee-structures` — no dedicated frontend form for this
was built in this plan; use curl or the DRF browsable API at
`http://localhost:8080/api/v1/finance/fee-structures` if available, or a
follow-up task can add an admin-facing form), pick it, approve. Confirm the
allocation appears and an invoice is created. Log in as the student, pay the
invoice via the existing pay flow, confirm a "Download receipt" button
appears and downloads a real PDF with a QR code visible. Scan or copy the
`verify_url` from the PDF, open it while logged in as warden, confirm it
shows "Valid receipt" with the correct amount/purpose/university name.

- [ ] **Step 8: Commit**

```bash
git add "frontend/su-erp-web/src/app/(dashboard)/student/page.tsx" \
        "frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx" \
        "frontend/su-erp-web/src/app/(dashboard)/verify-receipt/page.tsx" \
        services/finance-service/billing/views.py \
        services/finance-service/billing/urls.py \
        services/finance-service/billing/tests/test_receipts.py
git commit -m "feat(frontend): room-request UI, warden approval queue, receipt download, verify page"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1-2 cover student room-request creation + warden
  approve/reject (README design bullet 2, paragraphs 1-2). Task 3 covers
  configurable `FeeStructure` CRUD (bullet 2, paragraph 3). Task 4 wires the
  chosen fee + university name into invoice creation (bullet 2, paragraph 3
  continued). Task 5 covers PDF+QR+HMAC receipt generation and the
  download/verify endpoints (bullet 2, paragraph 4). Task 6 covers all
  frontend surfaces: student request form, warden approval queue with fee
  picker, receipt download, and the verify page (requiring warden/admin
  login, per the locked design decision).
- **No admin-facing FeeStructure-creation UI was built** — Task 6 Step 7
  flags this explicitly as a manual/curl step for now, since the original
  design only specified "warden manages FeeStructure separately (admin-style
  settings page)" without a concrete UI mockup being approved. This is a
  reasonable, explicitly-flagged gap rather than a silent one; a follow-up
  task can add a simple create form to the admin dashboard
  (`frontend/su-erp-web/src/app/(dashboard)/admin/page.tsx`) using the exact
  same `FeeStructureCreateSerializer` shape Task 3 already built, if wanted.
- **Type consistency checked:** `create_allocation`'s new
  `fee_structure_id`/`university_name` parameters (Task 2) match the exact
  keys (`fee_structure_id`, `university_name`) read by
  `handle_allocation_requested` (Task 4) off the event payload. `Receipt`
  field names (`pdf_data`, `verification_token`, `verify_url`) are identical
  across the model (Task 5), `billing/receipts.py` (Task 5), `ReceiptPdfView`/
  `VerifyReceiptView`/`ReceiptPdfByInvoiceView` (Task 5/6), and the frontend
  `VerifyResult` interface (Task 6) field names (`valid`, `receipt_no`,
  `amount`, `purpose`, `university_name`, `paid_on`) match
  `VerifyReceiptView`'s exact response dict keys.
- **No placeholders:** every step has complete, runnable code — including
  the full `reportlab`/`qrcode` PDF-rendering implementation, not a
  "render the PDF here" stub.
- **Known architecture trade-off, stated explicitly for the next reader:**
  Task 2's `resolve_institution_name` can silently return `""` on any
  failure (network blip, auth-service down) rather than blocking approval —
  this was a deliberate choice (a missing university name on a receipt is
  cosmetic) but means a transient auth-service outage at approval time
  produces receipts with a blank university name permanently (no retry).
  Acceptable for this scope; flagging so it isn't mistaken for an oversight.
