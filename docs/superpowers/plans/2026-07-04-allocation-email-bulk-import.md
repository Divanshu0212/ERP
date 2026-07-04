# Allocation by Email + Bulk Import + Hostel Setup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a warden allocate hostel rooms by student email (single or bulk CSV/XLSX upload, with a persisted per-batch/per-row log), and let an admin create the blocks/rooms that allocation depends on — all currently missing or UUID-only.

**Architecture:** One new auth-service endpoint (`GET /accounts/users/by-email/`) is the single source of truth for email→`User.id` resolution, since `student_id` throughout this platform IS the auth `User.id` (confirmed via the finance→notification event chain — see the design spec). hostel-service calls it synchronously through the gateway (the platform's first sync inter-service HTTP call) to resolve both student and warden emails. Bulk import parses CSV/XLSX synchronously in the request, creating each allocation in its own transaction via a `create_allocation` helper shared with the single-create endpoint, and logs every row's outcome.

**Tech Stack:** Django REST Framework (auth-service, hostel-service), `suerp_common` (JWT auth, tenancy, envelope, outbox), `requests` (new, sync HTTP), `openpyxl` (new, XLSX parsing), Next.js/React/TypeScript frontend with Vitest + Testing Library.

**Design spec:** `docs/superpowers/specs/2026-07-04-allocation-email-bulk-import-design.md`

## Global Constraints

- Every DRF response uses the shared envelope (`suerp_common.envelope.ok`/`fail`) — never a raw `Response`.
- Every new hostel-service/auth-service view must declare `permission_classes` explicitly (no relying on the `IsAuthenticated` default) matching the spec's role restrictions.
- `TenantModel.objects` is auto-tenant-scoped; only use `all_objects` outside request context (not applicable here — everything in this plan runs inside request-scoped views).
- The email lookup (`resolve_user_by_email`) always forwards the ORIGINAL caller's `Authorization` header — never mints or reuses a service credential.
- No changes to student-service (confirmed unnecessary by the design spec).
- Follow existing per-service test conventions: hostel-service tests mint JWTs directly with `jwt.encode` (it only verifies tokens); auth-service tests go through the real `register`/`login` endpoints (it issues tokens).
- Frontend tests use Vitest + Testing Library, mocking `@/lib/api`'s `api.get`/`api.post`/`api.upload` per the existing pattern in `warden.test.tsx`/`admin.test.tsx`.

---

## Task 1: auth-service — `GET /accounts/users/by-email/`

**Files:**
- Modify: `services/auth-service/accounts/views.py`
- Modify: `services/auth-service/accounts/urls.py`
- Modify: `services/auth-service/accounts/serializers.py`
- Test: `services/auth-service/accounts/tests/test_user_by_email.py` (new)

**Interfaces:**
- Produces: `GET /api/v1/auth/users/by-email/?email=<email>` → `warden`/`admin` only, tenant-scoped. 200 `{id, email, role}` on match, 404 on no match, 400 on missing `email` query param.

- [ ] **Step 1: Write the failing tests**

Create `services/auth-service/accounts/tests/test_user_by_email.py`:

```python
"""GET /auth/users/by-email/ — resolve an email to its User.id within the
caller's own tenant. Every student_id/warden_id in this platform IS the
auth-service User.id (see the design spec), so this single endpoint is
the whole identity-resolution story for hostel-service's email-based
allocation and block-creation flows.
"""

import pytest
from accounts.models import Institution, User
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

ENDPOINT = "/api/v1/auth/users/by-email/"


def _make_institution(slug="alpha", name="Alpha University"):
    return Institution.objects.create(slug=slug, name=name, is_active=True)


@pytest.fixture
def client():
    return APIClient()


def _register(client, institution, email, password="s3cur3-passw0rd", role=None):
    payload = {"institution_slug": institution.slug, "email": email, "password": password}
    if role is not None:
        payload["role"] = role
    resp = client.post("/api/v1/auth/register", payload, format="json")
    assert resp.status_code == 201, resp.content
    return resp.json()["data"]


def _token(client, institution, email, password="s3cur3-passw0rd"):
    resp = client.post(
        "/api/v1/auth/login",
        {"institution_slug": institution.slug, "email": email, "password": password},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    return resp.json()["data"]["access"]


def _warden_token(client, institution, email="warden@example.com"):
    _register(client, institution, email=email, role=User.Role.WARDEN)
    return _token(client, institution, email)


def test_warden_finds_student_by_email(client):
    inst = _make_institution()
    warden_token = _warden_token(client, inst)
    student = _register(client, inst, email="student@example.com", role=User.Role.STUDENT)

    resp = client.get(
        f"{ENDPOINT}?email=student@example.com",
        HTTP_AUTHORIZATION=f"Bearer {warden_token}",
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"] == {"id": student["id"], "email": "student@example.com", "role": "student"}


def test_returns_404_for_unknown_email(client):
    inst = _make_institution()
    warden_token = _warden_token(client, inst)

    resp = client.get(
        f"{ENDPOINT}?email=nobody@example.com",
        HTTP_AUTHORIZATION=f"Bearer {warden_token}",
    )

    assert resp.status_code == 404
    assert resp.json()["success"] is False


def test_lookup_is_tenant_scoped(client):
    inst_a = _make_institution(slug="alpha", name="Alpha University")
    inst_b = _make_institution(slug="beta", name="Beta University")
    warden_token = _warden_token(client, inst_a)
    _register(client, inst_b, email="student@example.com", role=User.Role.STUDENT)

    resp = client.get(
        f"{ENDPOINT}?email=student@example.com",
        HTTP_AUTHORIZATION=f"Bearer {warden_token}",
    )

    assert resp.status_code == 404


def test_student_role_cannot_use_lookup(client):
    inst = _make_institution()
    _register(client, inst, email="student@example.com", role=User.Role.STUDENT)
    student_token = _token(client, inst, "student@example.com")

    resp = client.get(
        f"{ENDPOINT}?email=student@example.com",
        HTTP_AUTHORIZATION=f"Bearer {student_token}",
    )

    assert resp.status_code == 403


def test_missing_email_param_is_400(client):
    inst = _make_institution()
    warden_token = _warden_token(client, inst)

    resp = client.get(ENDPOINT, HTTP_AUTHORIZATION=f"Bearer {warden_token}")

    assert resp.status_code == 400


def test_requires_authentication(client):
    resp = client.get(f"{ENDPOINT}?email=student@example.com")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd services/auth-service && pytest accounts/tests/test_user_by_email.py -v`
Expected: FAIL — 404 "Not Found" (route doesn't exist) for every test.

- [ ] **Step 3: Add `UserByEmailSerializer`**

In `services/auth-service/accounts/serializers.py`, add after `UserListSerializer`:

```python
class UserByEmailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    role = serializers.CharField()
```

- [ ] **Step 4: Add `UserByEmailView`**

In `services/auth-service/accounts/views.py`, add the import and the view (after `UserAdminView`):

```python
from accounts.serializers import (
    AdminCreateUserSerializer,
    InstitutionCreateSerializer,
    InstitutionSerializer,
    LoginSerializer,
    MeSerializer,
    RefreshSerializer,
    RegisterSerializer,
    SuperadminCreateAdminSerializer,
    UserByEmailSerializer,
    UserListSerializer,
)
```

```python
class UserByEmailView(APIView):
    """GET /api/v1/auth/users/by-email/?email=... — resolve an email to its
    User.id within the caller's own tenant.

    This is the platform's single identity-resolution endpoint: every
    student_id/warden_id elsewhere IS this User.id (see docs/superpowers/
    specs/2026-07-04-allocation-email-bulk-import-design.md), so
    hostel-service calls this endpoint (through the gateway, forwarding the
    caller's own token) to turn a warden-typed email into the UUID its
    Allocation/Block rows actually store.
    """

    permission_classes = [role_required("warden", "admin")]

    def get(self, request):
        email = request.query_params.get("email", "").strip()
        if not email:
            return fail("Query parameter 'email' is required.", status=400)

        email = User.objects.normalize_email(email)
        try:
            user = User.objects.get(tenant_id=request.user.tenant_id, email__iexact=email)
        except User.DoesNotExist:
            return fail(f"No user found with email {email}.", status=404)

        return ok(UserByEmailSerializer({"id": user.id, "email": user.email, "role": user.role}).data)
```

- [ ] **Step 5: Wire the URL**

In `services/auth-service/accounts/urls.py`:

```python
"""Auth endpoints: register, login, refresh, me, institution, users."""

from accounts.views import (
    InstitutionView,
    LoginView,
    MeView,
    PlatformAdminView,
    PlatformInstitutionView,
    RefreshView,
    RegisterView,
    UserAdminView,
    UserByEmailView,
)
from django.urls import path

urlpatterns = [
    path("register", RegisterView.as_view(), name="auth-register"),
    path("login", LoginView.as_view(), name="auth-login"),
    path("refresh", RefreshView.as_view(), name="auth-refresh"),
    path("me", MeView.as_view(), name="auth-me"),
    path("institution", InstitutionView.as_view(), name="auth-institution"),
    path("users", UserAdminView.as_view(), name="auth-users"),
    path("users/by-email/", UserByEmailView.as_view(), name="auth-user-by-email"),
    path("institutions", PlatformInstitutionView.as_view(), name="auth-institutions"),
    path("admins", PlatformAdminView.as_view(), name="auth-admins"),
]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd services/auth-service && pytest accounts/tests/test_user_by_email.py -v`
Expected: PASS (7 passed).

- [ ] **Step 7: Run the full auth-service test suite (no regressions)**

Run: `cd services/auth-service && pytest -q`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add services/auth-service/accounts/views.py services/auth-service/accounts/urls.py services/auth-service/accounts/serializers.py services/auth-service/accounts/tests/test_user_by_email.py
git commit -m "feat(auth): add warden/admin email-to-user-id lookup endpoint"
```

---

## Task 2: hostel-service — `resolve_user_by_email` lookup helper

**Files:**
- Create: `services/hostel-service/hostel/lookups.py`
- Modify: `services/hostel-service/config/settings.py`
- Modify: `services/hostel-service/requirements.txt`
- Modify: `infra/docker-compose.yml`
- Test: `services/hostel-service/hostel/tests/test_lookups.py` (new)

**Interfaces:**
- Produces: `resolve_user_by_email(email: str, auth_header: str | None) -> dict` (returns `{id, email, role}`); `LookupFailed(reason: "not_found" | "unavailable", detail: str)` exception. Consumed by Task 4 (`AllocateView`), Task 6 (`AllocateBulkView`), Task 8 (`BlockListCreateView`).

- [ ] **Step 1: Add `GATEWAY_URL` setting**

In `services/hostel-service/config/settings.py`, after the `RABBITMQ_URL` line at the end of the file, add:

```python

# --- Inter-service HTTP (email lookups) --------------------------------------
# The only synchronous inter-service call in the Django services: resolving a
# warden-typed email to its auth-service User.id. See hostel/lookups.py.
GATEWAY_URL = env("GATEWAY_URL", default="http://gateway:8080")
```

- [ ] **Step 2: Add dependencies**

In `services/hostel-service/requirements.txt`, add two lines after `psycopg[binary]`:

```
psycopg[binary]
requests
openpyxl
django-prometheus
```

(i.e. insert `requests` and `openpyxl` into the existing list; exact position doesn't matter.)

Run: `cd services/hostel-service && pip install -r requirements.txt`
Expected: `requests` and `openpyxl` install successfully.

- [ ] **Step 3: Add `GATEWAY_URL` to docker-compose's shared Django env**

In `infra/docker-compose.yml`, in the `x-django-env: &django-env` anchor block, add one line:

```yaml
x-django-env: &django-env
  SECRET_KEY: dev-insecure-secret-key
  DEBUG: "1"
  ALLOWED_HOSTS: "*"
  JWT_SIGNING_KEY: dev-insecure-shared-jwt-key
  REDIS_URL: redis://redis:6379/0
  RABBITMQ_URL: amqp://guest:guest@rabbitmq:5672/
  GATEWAY_URL: http://gateway:8080
```

- [ ] **Step 4: Write the failing tests**

Create `services/hostel-service/hostel/tests/test_lookups.py`:

```python
"""hostel/lookups.py — the platform's first synchronous inter-service call.

Mocks ``requests.get`` directly rather than hitting a real auth-service, since
this is a unit test of the HTTP-calling logic (status/timeout/parse handling),
not an integration test of auth-service itself.
"""

from unittest.mock import Mock, patch

import pytest
import requests
from hostel.lookups import LookupFailed, resolve_user_by_email


def _response(status_code, json_body=None):
    resp = Mock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = json_body or {}
    return resp


@patch("hostel.lookups.requests.get")
def test_resolves_email_on_success(mock_get):
    mock_get.return_value = _response(
        200, {"success": True, "data": {"id": "u1", "email": "a@example.com", "role": "student"}}
    )

    result = resolve_user_by_email("a@example.com", "Bearer tok")

    assert result == {"id": "u1", "email": "a@example.com", "role": "student"}
    called_url, called_kwargs = mock_get.call_args
    assert called_kwargs["params"] == {"email": "a@example.com"}
    assert called_kwargs["headers"] == {"Authorization": "Bearer tok"}
    assert called_kwargs["timeout"] == 5


@patch("hostel.lookups.requests.get")
def test_raises_not_found_on_404(mock_get):
    mock_get.return_value = _response(404)

    with pytest.raises(LookupFailed) as exc_info:
        resolve_user_by_email("nobody@example.com", "Bearer tok")

    assert exc_info.value.reason == "not_found"


@patch("hostel.lookups.requests.get")
def test_raises_unavailable_on_non_2xx(mock_get):
    mock_get.return_value = _response(500)

    with pytest.raises(LookupFailed) as exc_info:
        resolve_user_by_email("a@example.com", "Bearer tok")

    assert exc_info.value.reason == "unavailable"


@patch("hostel.lookups.requests.get")
def test_raises_unavailable_on_timeout(mock_get):
    mock_get.side_effect = requests.Timeout("timed out")

    with pytest.raises(LookupFailed) as exc_info:
        resolve_user_by_email("a@example.com", "Bearer tok")

    assert exc_info.value.reason == "unavailable"


@patch("hostel.lookups.requests.get")
def test_works_without_auth_header(mock_get):
    mock_get.return_value = _response(
        200, {"success": True, "data": {"id": "u1", "email": "a@example.com", "role": "student"}}
    )

    resolve_user_by_email("a@example.com", None)

    assert mock_get.call_args.kwargs["headers"] == {}
```

- [ ] **Step 5: Run to verify failure**

Run: `cd services/hostel-service && pytest hostel/tests/test_lookups.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'hostel.lookups'`.

- [ ] **Step 6: Implement `hostel/lookups.py`**

```python
"""Synchronous cross-service lookup: resolve a user's email to their
auth-service User.id.

hostel-service has no user table of its own (every service verifies JWTs
issued by auth-service — see suerp_common.auth — and never owns identity).
The warden's allocation and block-creation forms accept a student/warden
EMAIL rather than a raw UUID, so this makes exactly one synchronous HTTP
call through the gateway to auth-service's GET /accounts/users/by-email/
endpoint, forwarding the caller's own bearer token unchanged (that endpoint
is warden/admin-only, so the caller must already hold a token with
sufficient privilege — there is no separate service-to-service credential).

This is the first synchronous inter-service call among the Django
services; every other cross-service reference in this platform flows
through the async transactional-outbox/inbox pattern in suerp_common. It
stays narrow and local to hostel-service rather than becoming a shared
library, since no other service needs it today.
"""

import requests
from django.conf import settings


class LookupFailed(Exception):
    """Raised when a by-email lookup can't be resolved.

    ``reason`` is "not_found" (the email doesn't match any user in the
    caller's tenant — a 400 to the caller) or "unavailable" (timeout,
    connection error, or a non-2xx/non-404 from auth-service — a 502,
    since we can't tell whether the email itself is valid).
    """

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(detail or reason)


def resolve_user_by_email(email: str, auth_header: str | None) -> dict:
    """Resolve ``email`` to ``{id, email, role}`` via auth-service.

    ``auth_header`` is the inbound request's full ``Authorization: Bearer
    <token>`` value, forwarded unchanged so auth-service's own
    role_required("warden", "admin") check applies to the ORIGINAL caller.
    """
    url = f"{settings.GATEWAY_URL}/api/v1/auth/users/by-email/"
    headers = {"Authorization": auth_header} if auth_header else {}

    try:
        response = requests.get(url, params={"email": email}, headers=headers, timeout=5)
    except requests.RequestException as exc:
        raise LookupFailed("unavailable", str(exc)) from exc

    if response.status_code == 404:
        raise LookupFailed("not_found", f"No user found with email {email}.")
    if not response.ok:
        raise LookupFailed("unavailable", f"auth-service returned {response.status_code}.")

    try:
        envelope = response.json()
    except ValueError as exc:
        raise LookupFailed("unavailable", "Invalid response from auth-service.") from exc

    if not envelope.get("success"):
        raise LookupFailed("not_found", envelope.get("message") or f"No user found with email {email}.")

    return envelope["data"]
```

- [ ] **Step 7: Run to verify pass**

Run: `cd services/hostel-service && pytest hostel/tests/test_lookups.py -v`
Expected: PASS (5 passed).

- [ ] **Step 8: Commit**

```bash
git add services/hostel-service/hostel/lookups.py services/hostel-service/hostel/tests/test_lookups.py services/hostel-service/config/settings.py services/hostel-service/requirements.txt infra/docker-compose.yml
git commit -m "feat(hostel): add auth-service email lookup helper"
```

---

## Task 3: hostel-service — extract `create_allocation` into `hostel/services.py`

Pure refactor: move the existing lock/capacity-check/atomic-commit/outbox logic out of `AllocateView.post` into a standalone function, with zero behavior change, so Task 4 and Task 6 can both call it. The existing test suite (`test_allocate.py`) is the regression check — it must pass unmodified.

**Files:**
- Create: `services/hostel-service/hostel/services.py`
- Modify: `services/hostel-service/hostel/views.py`

**Interfaces:**
- Produces: `create_allocation(room_id, student_id, tenant_id) -> Allocation` (raises `django.http.Http404` if the room doesn't exist/isn't in this tenant, `RoomFullError` if it has no free capacity). Consumed by Task 4, Task 6.

- [ ] **Step 1: Confirm the current baseline passes**

Run: `cd services/hostel-service && pytest hostel/tests/test_allocate.py -v`
Expected: PASS (5 passed) — this is the safety net for the refactor.

- [ ] **Step 2: Create `hostel/services.py`**

```python
"""Allocation creation, shared by the single-create and bulk-import
endpoints (hostel/views.py: AllocateView, AllocateBulkView).

Extracted from AllocateView (Task 4.8) unchanged, so AllocateBulkView can
reuse the exact same lock/capacity-check/atomic-commit/outbox logic per
row instead of duplicating it. ``select_for_update()`` on the Room row
prevents concurrent over-allocation: two simultaneous calls against the
same last-open bed serialize on the row lock, so the second one observes
the incremented ``occupied_count`` and correctly raises ``RoomFullError``
instead of double-booking. State change and the ``hostel.allocation.
requested`` outbox event commit or roll back together (transactional-
outbox guarantee) — nothing here talks to RabbitMQ directly,
``drain_outbox_task`` relays it later.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from hostel.models import Allocation, Room
from suerp_common.outbox import publish_event


class RoomFullError(Exception):
    """Raised when the target room has no free capacity."""


def create_allocation(room_id, student_id, tenant_id) -> Allocation:
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
            },
        )

        return allocation
```

- [ ] **Step 3: Update `AllocateView.post` to call it**

In `services/hostel-service/hostel/views.py`, replace the whole `AllocateView` class body with:

```python
from hostel.services import RoomFullError, create_allocation


class AllocateView(APIView):
    permission_classes = [role_required("warden", "admin")]

    def post(self, request):
        serializer = AllocateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid allocation request.", errors=serializer.errors, status=400)

        room_id = serializer.validated_data["room_id"]
        student_id = serializer.validated_data["student_id"]

        try:
            allocation = create_allocation(room_id, student_id, get_current_tenant())
        except RoomFullError:
            return fail("Room at full capacity.", status=400)

        return ok(
            AllocationSerializer(allocation).data,
            message="Allocation created.",
            status=201,
        )
```

Remove the now-unused imports from the top of `views.py`: `from django.db import transaction`, `from django.shortcuts import get_object_or_404`, and the `Allocation` import stays (still used by `AllocationListView`/`AllocationSerializer`), but drop `publish_event` if nothing else in the file uses it yet (Task 6/7/8 will re-add imports as needed — leave only what's used after this step).

- [ ] **Step 4: Run the existing tests — must pass unchanged**

Run: `cd services/hostel-service && pytest hostel/tests/test_allocate.py -v`
Expected: PASS (5 passed), identical to Step 1 — confirms the refactor is behavior-preserving.

- [ ] **Step 5: Run the full hostel-service suite**

Run: `cd services/hostel-service && pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add services/hostel-service/hostel/services.py services/hostel-service/hostel/views.py
git commit -m "refactor(hostel): extract create_allocation for reuse by bulk import"
```

---

## Task 4: hostel-service — switch `AllocateView` to `student_email`

**Files:**
- Modify: `services/hostel-service/hostel/serializers.py`
- Modify: `services/hostel-service/hostel/views.py`
- Modify: `services/hostel-service/hostel/tests/test_allocate.py`

**Interfaces:**
- Consumes: `resolve_user_by_email` (Task 2), `create_allocation`/`RoomFullError` (Task 3).
- Produces: `POST /api/v1/hostel/allocate` now accepts `{room_id, student_email}` instead of `{room_id, student_id}`.

- [ ] **Step 1: Update the existing tests to the new request shape**

In `services/hostel-service/hostel/tests/test_allocate.py`, this endpoint's request body changes shape platform-wide (no backward-compat needed — see Global Constraints, no feature flags). Replace every `{"room_id": ..., "student_id": ...}` POST body with an email-based one, and mock the lookup. Add these imports at the top:

```python
from unittest.mock import patch
```

Replace `test_allocating_available_room_creates_pending_allocation_and_emits_event`:

```python
@patch("hostel.views.resolve_user_by_email")
def test_allocating_available_room_creates_pending_allocation_and_emits_event(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    student_id = uuid.uuid4()
    mock_resolve.return_value = {"id": str(student_id), "email": "student@example.com", "role": "student"}
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {"room_id": str(room.id), "student_email": "student@example.com"},
        format="json",
    )

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["status"] == "pending"
    assert body["data"]["room_id"] == str(room.id)
    assert body["data"]["student_id"] == str(student_id)
    mock_resolve.assert_called_once()

    allocations = Allocation.all_objects.filter(room=room, student_id=student_id)
    assert allocations.count() == 1
    allocation = allocations.first()
    assert allocation.status == "pending"

    room.refresh_from_db()
    assert room.occupied_count == 1

    events = OutboxEvent.objects.filter(type="hostel.allocation.requested")
    assert events.count() == 1
    event = events.first()
    assert str(event.tenant_id) == str(tenant_id)
    assert event.payload == {
        "allocation_id": str(allocation.id),
        "student_id": str(student_id),
        "room_id": str(room.id),
    }
```

Replace `test_allocating_full_room_returns_400_and_creates_nothing`:

```python
@patch("hostel.views.resolve_user_by_email")
def test_allocating_full_room_returns_400_and_creates_nothing(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=2)
    mock_resolve.return_value = {"id": str(uuid.uuid4()), "email": "student@example.com", "role": "student"}
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {"room_id": str(room.id), "student_email": "student@example.com"},
        format="json",
    )

    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert "capacity" in body["message"].lower()

    assert Allocation.all_objects.filter(room=room).count() == 0

    room.refresh_from_db()
    assert room.occupied_count == 2

    assert OutboxEvent.objects.filter(type="hostel.allocation.requested").count() == 0
```

Replace `test_student_role_cannot_allocate` (no mock needed — permission check happens before lookup):

```python
def test_student_role_cannot_allocate():
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    client = _auth_client(tenant_id, role="student")

    response = client.post(
        "/api/v1/hostel/allocate",
        {"room_id": str(room.id), "student_email": "student@example.com"},
        format="json",
    )

    assert response.status_code == 403
    assert Allocation.all_objects.filter(room=room).count() == 0
    assert OutboxEvent.objects.count() == 0
```

Replace `test_warden_cannot_allocate_room_from_a_different_tenant`:

```python
@patch("hostel.views.resolve_user_by_email")
def test_warden_cannot_allocate_room_from_a_different_tenant(mock_resolve):
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    room = _make_room(tenant_a, capacity=2, occupied_count=0)
    mock_resolve.return_value = {"id": str(uuid.uuid4()), "email": "student@example.com", "role": "student"}
    client_b = _auth_client(tenant_b, role="warden")

    response = client_b.post(
        "/api/v1/hostel/allocate",
        {"room_id": str(room.id), "student_email": "student@example.com"},
        format="json",
    )

    assert response.status_code == 404

    room.refresh_from_db()
    assert room.occupied_count == 0
    assert Allocation.all_objects.filter(room=room).count() == 0
    assert OutboxEvent.objects.count() == 0
```

Leave `test_available_rooms_lists_only_rooms_with_capacity_tenant_scoped` unchanged (unrelated to this endpoint).

Add two new tests at the end of the file:

```python
@patch("hostel.views.resolve_user_by_email")
def test_allocate_returns_400_when_email_not_found(mock_resolve):
    from hostel.lookups import LookupFailed

    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    mock_resolve.side_effect = LookupFailed("not_found", "No user found with email x@example.com.")
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {"room_id": str(room.id), "student_email": "x@example.com"},
        format="json",
    )

    assert response.status_code == 400
    assert Allocation.all_objects.filter(room=room).count() == 0


@patch("hostel.views.resolve_user_by_email")
def test_allocate_returns_502_when_lookup_service_unavailable(mock_resolve):
    from hostel.lookups import LookupFailed

    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    mock_resolve.side_effect = LookupFailed("unavailable", "auth-service returned 500.")
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/allocate",
        {"room_id": str(room.id), "student_email": "x@example.com"},
        format="json",
    )

    assert response.status_code == 502
    assert Allocation.all_objects.filter(room=room).count() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/hostel-service && pytest hostel/tests/test_allocate.py -v`
Expected: FAIL — `AllocateRequestSerializer` still requires `student_id`, so every request 400s as invalid, and `hostel.views.resolve_user_by_email` doesn't exist yet to patch.

- [ ] **Step 3: Update the serializer**

In `services/hostel-service/hostel/serializers.py`, change:

```python
class AllocateRequestSerializer(serializers.Serializer):
    room_id = serializers.UUIDField()
    student_email = serializers.EmailField()
```

- [ ] **Step 4: Update `AllocateView.post`**

In `services/hostel-service/hostel/views.py`, add the import:

```python
from hostel.lookups import LookupFailed, resolve_user_by_email
```

Replace `AllocateView.post` body:

```python
class AllocateView(APIView):
    permission_classes = [role_required("warden", "admin")]

    def post(self, request):
        serializer = AllocateRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid allocation request.", errors=serializer.errors, status=400)

        room_id = serializer.validated_data["room_id"]
        student_email = serializer.validated_data["student_email"]

        try:
            student = resolve_user_by_email(student_email, request.META.get("HTTP_AUTHORIZATION"))
        except LookupFailed as exc:
            return fail(str(exc), status=400 if exc.reason == "not_found" else 502)

        try:
            allocation = create_allocation(room_id, student["id"], get_current_tenant())
        except RoomFullError:
            return fail("Room at full capacity.", status=400)

        return ok(
            AllocationSerializer(allocation).data,
            message="Allocation created.",
            status=201,
        )
```

- [ ] **Step 5: Run to verify pass**

Run: `cd services/hostel-service && pytest hostel/tests/test_allocate.py -v`
Expected: PASS (7 passed).

- [ ] **Step 6: Commit**

```bash
git add services/hostel-service/hostel/serializers.py services/hostel-service/hostel/views.py services/hostel-service/hostel/tests/test_allocate.py
git commit -m "feat(hostel): allocate by student email instead of student_id"
```

---

## Task 5: hostel-service — `AllocationImportBatch`/`AllocationImportRow` models

**Files:**
- Modify: `services/hostel-service/hostel/models.py`
- Create: `services/hostel-service/hostel/migrations/0003_allocationimportbatch_allocationimportrow.py` (generated)
- Test: `services/hostel-service/hostel/tests/test_models.py`

**Interfaces:**
- Produces: `AllocationImportBatch` (`id, uploaded_by, filename, total_rows, success_count, fail_count, created_at`), `AllocationImportRow` (`id, batch (FK), row_number, room_id_raw, student_email_raw, status, error_message, allocation (nullable FK)`). Consumed by Task 6 (writes them), Task 7 (serializes/lists them).

- [ ] **Step 1: Add the models**

In `services/hostel-service/hostel/models.py`, add at the end of the file:

```python
class AllocationImportBatch(TenantModel):
    """One warden-initiated bulk-allocation upload (CSV or XLSX).

    ``success_count``/``fail_count`` are denormalized onto the batch (rather
    than always aggregating ``rows``) so the Import Logs list view can show
    them without an extra query per batch.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Reference to auth-service's User table (the warden/admin who uploaded).
    # Bare UUID — no cross-service FK (DB-per-service).
    uploaded_by = models.UUIDField()
    filename = models.CharField(max_length=255)
    total_rows = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    fail_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"ImportBatch {self.id} ({self.filename})"


class AllocationImportRow(TenantModel):
    """One row's outcome within an AllocationImportBatch."""

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(AllocationImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()
    room_id_raw = models.CharField(max_length=255)
    student_email_raw = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=Status.choices)
    error_message = models.CharField(max_length=500, blank=True, default="")
    allocation = models.ForeignKey(
        Allocation, on_delete=models.SET_NULL, null=True, blank=True, related_name="import_rows"
    )

    class Meta:
        ordering = ["row_number"]

    def __str__(self):
        return f"ImportRow {self.row_number} of batch {self.batch_id} ({self.status})"
```

- [ ] **Step 2: Generate the migration**

Run: `cd services/hostel-service && python manage.py makemigrations hostel`
Expected: creates `hostel/migrations/0003_allocationimportbatch_allocationimportrow.py`.

- [ ] **Step 3: Write a model test**

In `services/hostel-service/hostel/tests/test_models.py`, add (append if the file already has content; if it only has other models' tests, add this at the end):

```python
import uuid

import pytest
from hostel.models import Allocation, AllocationImportBatch, AllocationImportRow, Block, Room

pytestmark = pytest.mark.django_db


def test_import_batch_and_row_creation():
    tenant_id = uuid.uuid4()
    block = Block.all_objects.create(
        tenant_id=tenant_id, name="Block A", gender_type="M", warden_id=uuid.uuid4()
    )
    room = Room.all_objects.create(tenant_id=tenant_id, block=block, room_no="101", capacity=2)
    allocation = Allocation.all_objects.create(
        tenant_id=tenant_id, room=room, student_id=uuid.uuid4(), status=Allocation.Status.PENDING
    )

    batch = AllocationImportBatch.all_objects.create(
        tenant_id=tenant_id,
        uploaded_by=uuid.uuid4(),
        filename="import.csv",
        total_rows=2,
        success_count=1,
        fail_count=1,
    )
    success_row = AllocationImportRow.all_objects.create(
        tenant_id=tenant_id,
        batch=batch,
        row_number=1,
        room_id_raw=str(room.id),
        student_email_raw="a@example.com",
        status=AllocationImportRow.Status.SUCCESS,
        allocation=allocation,
    )
    failed_row = AllocationImportRow.all_objects.create(
        tenant_id=tenant_id,
        batch=batch,
        row_number=2,
        room_id_raw="not-a-uuid",
        student_email_raw="bad@example.com",
        status=AllocationImportRow.Status.FAILED,
        error_message="Room not found.",
    )

    assert list(batch.rows.order_by("row_number")) == [success_row, failed_row]
    assert success_row.allocation_id == allocation.id
    assert failed_row.allocation is None
```

- [ ] **Step 4: Run the test**

Run: `cd services/hostel-service && pytest hostel/tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `cd services/hostel-service && pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add services/hostel-service/hostel/models.py services/hostel-service/hostel/migrations/0003_allocationimportbatch_allocationimportrow.py services/hostel-service/hostel/tests/test_models.py
git commit -m "feat(hostel): add AllocationImportBatch/Row models for bulk-import logging"
```

---

## Task 6: hostel-service — `POST /hostel/allocate/bulk`

**Files:**
- Modify: `services/hostel-service/hostel/views.py`
- Modify: `services/hostel-service/hostel/urls.py`
- Test: `services/hostel-service/hostel/tests/test_allocate_bulk.py` (new)

**Interfaces:**
- Consumes: `resolve_user_by_email`/`LookupFailed` (Task 2), `create_allocation`/`RoomFullError` (Task 3), `AllocationImportBatch`/`AllocationImportRow` (Task 5).
- Produces: `POST /api/v1/hostel/allocate/bulk` (multipart, field name `file`) → `{batch_id, total_rows, success_count, fail_count}`.

- [ ] **Step 1: Write the failing tests**

Create `services/hostel-service/hostel/tests/test_allocate_bulk.py`:

```python
"""POST /api/v1/hostel/allocate/bulk — CSV/XLSX bulk allocation.

Each row is processed independently (its own try/except around
create_allocation), so a bad row never aborts the batch — the response and
the persisted AllocationImportBatch/Row log always report a mix of
success/fail counts.
"""

import io
import uuid
from unittest.mock import patch

import openpyxl
import pytest
from hostel.models import Allocation, AllocationImportBatch, AllocationImportRow, Room
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

from hostel.tests.test_allocate import _auth_client, _make_room  # noqa: E402


def _csv_file(rows, filename="import.csv"):
    lines = ["room_id,student_email"] + [f"{r},{e}" for r, e in rows]
    content = "\n".join(lines).encode("utf-8")
    return io.BytesIO(content), filename


def _xlsx_file(rows, filename="import.xlsx"):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["room_id", "student_email"])
    for r, e in rows:
        sheet.append([r, e])
    buf = io.BytesIO()
    workbook.save(buf)
    buf.seek(0)
    return buf, filename


def _upload(client, buf, filename):
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile(filename, buf.read())
    return client.post("/api/v1/hostel/allocate/bulk", {"file": upload}, format="multipart")


@patch("hostel.views.resolve_user_by_email")
def test_all_rows_succeed_csv(mock_resolve):
    tenant_id = uuid.uuid4()
    room1 = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    room2 = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="102")
    mock_resolve.side_effect = lambda email, auth: {"id": str(uuid.uuid4()), "email": email, "role": "student"}
    client = _auth_client(tenant_id, role="warden")

    buf, name = _csv_file([(str(room1.id), "a@example.com"), (str(room2.id), "b@example.com")])
    response = _upload(client, buf, name)

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["total_rows"] == 2
    assert body["success_count"] == 2
    assert body["fail_count"] == 0

    batch = AllocationImportBatch.all_objects.get(id=body["batch_id"])
    assert batch.filename == name
    assert batch.rows.filter(status="success").count() == 2
    assert Allocation.all_objects.filter(tenant_id=tenant_id).count() == 2


@patch("hostel.views.resolve_user_by_email")
def test_all_rows_succeed_xlsx(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0)
    mock_resolve.return_value = {"id": str(uuid.uuid4()), "email": "a@example.com", "role": "student"}
    client = _auth_client(tenant_id, role="warden")

    buf, name = _xlsx_file([(str(room.id), "a@example.com")])
    response = _upload(client, buf, name)

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["success_count"] == 1
    assert body["fail_count"] == 0


@patch("hostel.views.resolve_user_by_email")
def test_mixed_success_and_failure(mock_resolve):
    from hostel.lookups import LookupFailed

    tenant_id = uuid.uuid4()
    good_room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    full_room = _make_room(tenant_id, capacity=1, occupied_count=1, room_no="102")

    def resolve_side_effect(email, auth):
        if email == "unknown@example.com":
            raise LookupFailed("not_found", "No user found.")
        return {"id": str(uuid.uuid4()), "email": email, "role": "student"}

    mock_resolve.side_effect = resolve_side_effect
    client = _auth_client(tenant_id, role="warden")

    buf, name = _csv_file(
        [
            (str(good_room.id), "good@example.com"),
            (str(full_room.id), "student2@example.com"),
            ("not-a-uuid", "student3@example.com"),
            (str(good_room.id), "unknown@example.com"),
        ]
    )
    response = _upload(client, buf, name)

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["total_rows"] == 4
    assert body["success_count"] == 1
    assert body["fail_count"] == 3

    batch = AllocationImportBatch.all_objects.get(id=body["batch_id"])
    rows = list(batch.rows.order_by("row_number"))
    assert rows[0].status == "success"
    assert rows[1].status == "failed" and "capacity" in rows[1].error_message.lower()
    assert rows[2].status == "failed"
    assert rows[3].status == "failed" and "no user found" in rows[3].error_message.lower()


def test_rejects_wrong_extension():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="warden")

    buf, name = _csv_file([(str(uuid.uuid4()), "a@example.com")], filename="import.txt")
    response = _upload(client, buf, name)

    assert response.status_code == 415
    assert AllocationImportBatch.all_objects.count() == 0


def test_rejects_missing_columns():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="warden")

    content = io.BytesIO(b"foo,bar\n1,2\n")
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile("import.csv", content.read())
    response = client.post("/api/v1/hostel/allocate/bulk", {"file": upload}, format="multipart")

    assert response.status_code == 400
    assert AllocationImportBatch.all_objects.count() == 0


def test_student_role_cannot_bulk_allocate():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="student")

    buf, name = _csv_file([(str(uuid.uuid4()), "a@example.com")])
    response = _upload(client, buf, name)

    assert response.status_code == 403
    assert AllocationImportBatch.all_objects.count() == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/hostel-service && pytest hostel/tests/test_allocate_bulk.py -v`
Expected: FAIL — no `/allocate/bulk` route exists (404s).

- [ ] **Step 3: Implement `AllocateBulkView` and `_parse_rows`**

In `services/hostel-service/hostel/views.py`, add these imports at the top (alongside the existing ones):

```python
import csv
import io
import uuid as uuid_lib

import openpyxl
from django.http import Http404
from hostel.models import AllocationImportBatch, AllocationImportRow
from rest_framework.parsers import MultiPartParser
```

Add at the end of the file:

```python
ALLOWED_EXTENSIONS = {"csv", "xlsx"}


def _parse_rows(upload, extension) -> list[tuple[str, str]]:
    """Parse an uploaded CSV/XLSX into a list of (room_id, student_email) tuples.

    Expects a header row with columns ``room_id`` and ``student_email`` (any
    order, case-insensitive). Raises ValueError with a caller-facing message
    on missing/misnamed columns or an empty sheet.
    """
    if extension == "csv":
        text = upload.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
        if "room_id" not in fieldnames or "student_email" not in fieldnames:
            raise ValueError("CSV must have room_id and student_email columns.")
        rows = []
        for record in reader:
            normalized = {k.strip().lower(): v for k, v in record.items() if k}
            rows.append(
                (
                    (normalized.get("room_id") or "").strip(),
                    (normalized.get("student_email") or "").strip(),
                )
            )
        return rows

    workbook = openpyxl.load_workbook(upload, read_only=True, data_only=True)
    sheet = workbook.active
    sheet_rows = list(sheet.iter_rows(values_only=True))
    if not sheet_rows:
        raise ValueError("XLSX file is empty.")
    header = [str(c).strip().lower() if c is not None else "" for c in sheet_rows[0]]
    if "room_id" not in header or "student_email" not in header:
        raise ValueError("XLSX must have room_id and student_email columns.")
    room_idx = header.index("room_id")
    email_idx = header.index("student_email")
    rows = []
    for record in sheet_rows[1:]:
        if record is None or all(c is None for c in record):
            continue
        room_val = record[room_idx] if room_idx < len(record) else None
        email_val = record[email_idx] if email_idx < len(record) else None
        rows.append(
            (
                str(room_val).strip() if room_val is not None else "",
                str(email_val).strip() if email_val is not None else "",
            )
        )
    return rows


class AllocateBulkView(APIView):
    """POST /api/v1/hostel/allocate/bulk — CSV/XLSX bulk allocation.

    Runs synchronously within the request (no async worker/queue — see the
    design spec for why this matches the expected load). Each row is
    resolved and allocated independently; a bad row is recorded as a
    failed AllocationImportRow and processing continues, so the response
    always reports success_count/fail_count out of total_rows rather than
    failing the whole batch.
    """

    permission_classes = [role_required("warden", "admin")]
    parser_classes = [MultiPartParser]

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return fail("No file uploaded.", status=400)

        extension = upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
        if extension not in ALLOWED_EXTENSIONS:
            return fail("File must be .csv or .xlsx.", status=415)

        try:
            rows = _parse_rows(upload, extension)
        except ValueError as exc:
            return fail(str(exc), status=400)

        auth_header = request.META.get("HTTP_AUTHORIZATION")
        tenant_id = get_current_tenant()

        batch = AllocationImportBatch.objects.create(
            tenant_id=tenant_id,
            uploaded_by=request.user.id,
            filename=upload.name,
            total_rows=len(rows),
        )

        email_cache: dict[str, dict] = {}
        success_count = 0
        fail_count = 0

        for row_number, (room_id_raw, student_email_raw) in enumerate(rows, start=1):
            error_message = ""
            allocation = None
            try:
                if not room_id_raw or not student_email_raw:
                    raise ValueError("room_id and student_email are both required.")

                if student_email_raw not in email_cache:
                    email_cache[student_email_raw] = resolve_user_by_email(student_email_raw, auth_header)
                student = email_cache[student_email_raw]

                room_uuid = uuid_lib.UUID(room_id_raw)
                allocation = create_allocation(room_uuid, student["id"], tenant_id)
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
            except ValueError as exc:
                error_message = str(exc)
                fail_count += 1

            AllocationImportRow.objects.create(
                tenant_id=tenant_id,
                batch=batch,
                row_number=row_number,
                room_id_raw=room_id_raw,
                student_email_raw=student_email_raw,
                status=AllocationImportRow.Status.SUCCESS if allocation else AllocationImportRow.Status.FAILED,
                error_message=error_message,
                allocation=allocation,
            )

        batch.success_count = success_count
        batch.fail_count = fail_count
        batch.save(update_fields=["success_count", "fail_count"])

        return ok(
            {
                "batch_id": str(batch.id),
                "total_rows": len(rows),
                "success_count": success_count,
                "fail_count": fail_count,
            },
            message="Bulk import processed.",
            status=201,
        )
```

- [ ] **Step 4: Wire the URL**

In `services/hostel-service/hostel/urls.py`:

```python
"""Hostel endpoints: allocate, rooms/available, allocations, bulk import.

Included under /api/v1/hostel/ from config.urls.
"""

from django.urls import path
from hostel.views import AllocateBulkView, AllocateView, AllocationListView, AvailableRoomsView

urlpatterns = [
    path("allocate", AllocateView.as_view(), name="allocate"),
    path("allocate/bulk", AllocateBulkView.as_view(), name="allocate-bulk"),
    path("rooms/available", AvailableRoomsView.as_view(), name="rooms-available"),
    path("allocations", AllocationListView.as_view(), name="allocation-list"),
]
```

(Task 7 and Task 8 will add more imports/paths to this same file.)

- [ ] **Step 5: Run to verify pass**

Run: `cd services/hostel-service && pytest hostel/tests/test_allocate_bulk.py -v`
Expected: PASS (6 passed).

- [ ] **Step 6: Run the full suite**

Run: `cd services/hostel-service && pytest -q`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add services/hostel-service/hostel/views.py services/hostel-service/hostel/urls.py services/hostel-service/hostel/tests/test_allocate_bulk.py
git commit -m "feat(hostel): add CSV/XLSX bulk allocation endpoint"
```

---

## Task 7: hostel-service — Import Logs endpoints

**Files:**
- Modify: `services/hostel-service/hostel/serializers.py`
- Modify: `services/hostel-service/hostel/views.py`
- Modify: `services/hostel-service/hostel/urls.py`
- Test: `services/hostel-service/hostel/tests/test_import_logs.py` (new)

**Interfaces:**
- Produces: `GET /api/v1/hostel/allocations/import-logs` (paginated batch list), `GET /api/v1/hostel/allocations/import-logs/<uuid:pk>` (batch + its rows).

- [ ] **Step 1: Write the failing tests**

Create `services/hostel-service/hostel/tests/test_import_logs.py`:

```python
"""GET /api/v1/hostel/allocations/import-logs[/<id>] — bulk-import audit trail."""

import uuid

import pytest
from hostel.models import AllocationImportBatch, AllocationImportRow

pytestmark = pytest.mark.django_db

from hostel.tests.test_allocate import _auth_client  # noqa: E402


def _make_batch(tenant_id, filename="import.csv", total=2, success=1, fail=1):
    return AllocationImportBatch.all_objects.create(
        tenant_id=tenant_id,
        uploaded_by=uuid.uuid4(),
        filename=filename,
        total_rows=total,
        success_count=success,
        fail_count=fail,
    )


def test_list_returns_tenant_scoped_batches():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    _make_batch(tenant_a, filename="a.csv")
    _make_batch(tenant_b, filename="b.csv")
    client = _auth_client(tenant_a, role="warden")

    response = client.get("/api/v1/hostel/allocations/import-logs")

    assert response.status_code == 200
    results = response.json()["data"]["results"]
    assert [r["filename"] for r in results] == ["a.csv"]


def test_detail_includes_rows():
    tenant_id = uuid.uuid4()
    batch = _make_batch(tenant_id)
    AllocationImportRow.all_objects.create(
        tenant_id=tenant_id,
        batch=batch,
        row_number=1,
        room_id_raw=str(uuid.uuid4()),
        student_email_raw="a@example.com",
        status=AllocationImportRow.Status.SUCCESS,
    )
    AllocationImportRow.all_objects.create(
        tenant_id=tenant_id,
        batch=batch,
        row_number=2,
        room_id_raw="bad",
        student_email_raw="b@example.com",
        status=AllocationImportRow.Status.FAILED,
        error_message="Room not found.",
    )
    client = _auth_client(tenant_id, role="warden")

    response = client.get(f"/api/v1/hostel/allocations/import-logs/{batch.id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["filename"] == batch.filename
    assert len(data["rows"]) == 2
    assert data["rows"][1]["error_message"] == "Room not found."


def test_detail_404_for_other_tenant():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    batch = _make_batch(tenant_a)
    client = _auth_client(tenant_b, role="warden")

    response = client.get(f"/api/v1/hostel/allocations/import-logs/{batch.id}")

    assert response.status_code == 404


def test_student_role_cannot_view_logs():
    tenant_id = uuid.uuid4()
    _make_batch(tenant_id)
    client = _auth_client(tenant_id, role="student")

    response = client.get("/api/v1/hostel/allocations/import-logs")

    assert response.status_code == 403
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/hostel-service && pytest hostel/tests/test_import_logs.py -v`
Expected: FAIL — route doesn't exist.

- [ ] **Step 3: Add the serializers**

In `services/hostel-service/hostel/serializers.py`, add at the end:

```python
class AllocationImportRowSerializer(serializers.ModelSerializer):
    allocation_id = serializers.SerializerMethodField()

    class Meta:
        model = AllocationImportRow
        fields = ["row_number", "room_id_raw", "student_email_raw", "status", "error_message", "allocation_id"]
        read_only_fields = fields

    def get_allocation_id(self, obj):
        return str(obj.allocation_id) if obj.allocation_id else None


class AllocationImportBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = AllocationImportBatch
        fields = ["id", "filename", "total_rows", "success_count", "fail_count", "created_at"]
        read_only_fields = fields


class AllocationImportBatchDetailSerializer(AllocationImportBatchSerializer):
    rows = AllocationImportRowSerializer(many=True, read_only=True)

    class Meta(AllocationImportBatchSerializer.Meta):
        fields = AllocationImportBatchSerializer.Meta.fields + ["rows"]
```

Add the model import at the top of `serializers.py`:

```python
from hostel.models import Allocation, AllocationImportBatch, AllocationImportRow, Room
```

- [ ] **Step 4: Add the views**

In `services/hostel-service/hostel/views.py`, add the serializer imports and two views:

```python
from hostel.serializers import (
    AllocateRequestSerializer,
    AllocationImportBatchDetailSerializer,
    AllocationImportBatchSerializer,
    AllocationSerializer,
    RoomSerializer,
)
from rest_framework.generics import RetrieveAPIView
```

```python
class AllocationImportLogListView(ListAPIView):
    """GET /api/v1/hostel/allocations/import-logs — tenant-scoped, paginated."""

    serializer_class = AllocationImportBatchSerializer
    permission_classes = [role_required("warden", "admin")]

    def get_queryset(self):
        return AllocationImportBatch.objects.all()


class AllocationImportLogDetailView(RetrieveAPIView):
    """GET /api/v1/hostel/allocations/import-logs/<id> — batch + its rows."""

    serializer_class = AllocationImportBatchDetailSerializer
    permission_classes = [role_required("warden", "admin")]
    queryset = AllocationImportBatch.objects.all()
```

- [ ] **Step 5: Wire the URLs**

In `services/hostel-service/hostel/urls.py`:

```python
from hostel.views import (
    AllocateBulkView,
    AllocateView,
    AllocationImportLogDetailView,
    AllocationImportLogListView,
    AllocationListView,
    AvailableRoomsView,
)

urlpatterns = [
    path("allocate", AllocateView.as_view(), name="allocate"),
    path("allocate/bulk", AllocateBulkView.as_view(), name="allocate-bulk"),
    path("rooms/available", AvailableRoomsView.as_view(), name="rooms-available"),
    path("allocations", AllocationListView.as_view(), name="allocation-list"),
    path("allocations/import-logs", AllocationImportLogListView.as_view(), name="allocation-import-log-list"),
    path(
        "allocations/import-logs/<uuid:pk>",
        AllocationImportLogDetailView.as_view(),
        name="allocation-import-log-detail",
    ),
]
```

- [ ] **Step 6: Run to verify pass**

Run: `cd services/hostel-service && pytest hostel/tests/test_import_logs.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Run the full suite**

Run: `cd services/hostel-service && pytest -q`
Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add services/hostel-service/hostel/serializers.py services/hostel-service/hostel/views.py services/hostel-service/hostel/urls.py services/hostel-service/hostel/tests/test_import_logs.py
git commit -m "feat(hostel): add bulk-import log list/detail endpoints"
```

---

## Task 8: hostel-service — Block/Room create + list endpoints

**Files:**
- Modify: `services/hostel-service/hostel/serializers.py`
- Modify: `services/hostel-service/hostel/views.py`
- Modify: `services/hostel-service/hostel/urls.py`
- Test: `services/hostel-service/hostel/tests/test_blocks_rooms.py` (new)

**Interfaces:**
- Consumes: `resolve_user_by_email`/`LookupFailed` (Task 2).
- Produces: `POST/GET /api/v1/hostel/blocks` (admin only), `POST/GET /api/v1/hostel/rooms` (admin/warden). `RoomSerializer` gains a `block_name` field (used by the frontend room picker in Task 11).

- [ ] **Step 1: Write the failing tests**

Create `services/hostel-service/hostel/tests/test_blocks_rooms.py`:

```python
"""POST/GET /api/v1/hostel/blocks and /api/v1/hostel/rooms — hostel setup.

Without these, the only way to create a Room/Block is direct DB access
(fixtures/migrations/admin shell) — there is no API for it at all today.
"""

import uuid
from unittest.mock import patch

import pytest
from hostel.models import Block, Room

pytestmark = pytest.mark.django_db

from hostel.tests.test_allocate import _auth_client, _make_block  # noqa: E402


@patch("hostel.views.resolve_user_by_email")
def test_admin_creates_block(mock_resolve):
    tenant_id = uuid.uuid4()
    warden_id = uuid.uuid4()
    mock_resolve.return_value = {"id": str(warden_id), "email": "warden@example.com", "role": "warden"}
    client = _auth_client(tenant_id, role="admin")

    response = client.post(
        "/api/v1/hostel/blocks",
        {"name": "Block C", "gender_type": "F", "warden_email": "warden@example.com"},
        format="json",
    )

    assert response.status_code == 201, response.content
    data = response.json()["data"]
    assert data["name"] == "Block C"
    assert data["warden_id"] == str(warden_id)
    assert Block.all_objects.filter(tenant_id=tenant_id, name="Block C").exists()


def test_warden_cannot_create_block():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/blocks",
        {"name": "Block C", "gender_type": "F", "warden_email": "warden@example.com"},
        format="json",
    )

    assert response.status_code == 403


@patch("hostel.views.resolve_user_by_email")
def test_create_block_400_when_warden_email_not_found(mock_resolve):
    from hostel.lookups import LookupFailed

    tenant_id = uuid.uuid4()
    mock_resolve.side_effect = LookupFailed("not_found", "No user found.")
    client = _auth_client(tenant_id, role="admin")

    response = client.post(
        "/api/v1/hostel/blocks",
        {"name": "Block C", "gender_type": "F", "warden_email": "nobody@example.com"},
        format="json",
    )

    assert response.status_code == 400
    assert Block.all_objects.count() == 0


def test_list_blocks_is_tenant_scoped():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    _make_block(tenant_a)
    _make_block(tenant_b)
    client = _auth_client(tenant_a, role="admin")

    response = client.get("/api/v1/hostel/blocks")

    assert response.status_code == 200
    assert len(response.json()["data"]["results"]) == 1


def test_admin_creates_room():
    tenant_id = uuid.uuid4()
    block = _make_block(tenant_id)
    client = _auth_client(tenant_id, role="admin")

    response = client.post(
        "/api/v1/hostel/rooms",
        {"block_id": str(block.id), "room_no": "303", "capacity": 3},
        format="json",
    )

    assert response.status_code == 201, response.content
    data = response.json()["data"]
    assert data["room_no"] == "303"
    assert data["block_name"] == block.name
    assert Room.all_objects.filter(tenant_id=tenant_id, room_no="303").exists()


def test_warden_can_also_create_room():
    tenant_id = uuid.uuid4()
    block = _make_block(tenant_id)
    client = _auth_client(tenant_id, role="warden")

    response = client.post(
        "/api/v1/hostel/rooms",
        {"block_id": str(block.id), "room_no": "304"},
        format="json",
    )

    assert response.status_code == 201, response.content


def test_student_cannot_create_room():
    tenant_id = uuid.uuid4()
    block = _make_block(tenant_id)
    client = _auth_client(tenant_id, role="student")

    response = client.post(
        "/api/v1/hostel/rooms",
        {"block_id": str(block.id), "room_no": "305"},
        format="json",
    )

    assert response.status_code == 403


def test_create_room_404_for_block_in_other_tenant():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    block = _make_block(tenant_a)
    client = _auth_client(tenant_b, role="admin")

    response = client.post(
        "/api/v1/hostel/rooms",
        {"block_id": str(block.id), "room_no": "306"},
        format="json",
    )

    assert response.status_code == 404


def test_list_rooms_includes_block_name():
    tenant_id = uuid.uuid4()
    block = _make_block(tenant_id)
    Room.all_objects.create(tenant_id=tenant_id, block=block, room_no="401", capacity=2)
    client = _auth_client(tenant_id, role="admin")

    response = client.get("/api/v1/hostel/rooms")

    assert response.status_code == 200
    results = response.json()["data"]["results"]
    assert results[0]["block_name"] == block.name
```

- [ ] **Step 2: Run to verify failure**

Run: `cd services/hostel-service && pytest hostel/tests/test_blocks_rooms.py -v`
Expected: FAIL — routes don't exist yet.

- [ ] **Step 3: Update `RoomSerializer`, add `BlockSerializer`/`BlockCreateSerializer`/`RoomCreateSerializer`**

In `services/hostel-service/hostel/serializers.py`, update the model import to include `Block`:

```python
from hostel.models import Allocation, AllocationImportBatch, AllocationImportRow, Block, Room
```

Replace `RoomSerializer`:

```python
class RoomSerializer(serializers.ModelSerializer):
    is_available = serializers.BooleanField(read_only=True)
    block_name = serializers.CharField(source="block.name", read_only=True)

    class Meta:
        model = Room
        fields = ["id", "block", "block_name", "room_no", "capacity", "occupied_count", "is_available"]
        read_only_fields = fields
```

Add after it:

```python
class BlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = Block
        fields = ["id", "name", "gender_type", "warden_id", "created_at"]
        read_only_fields = fields


class BlockCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    gender_type = serializers.ChoiceField(choices=Block.GenderType.choices)
    warden_email = serializers.EmailField()


class RoomCreateSerializer(serializers.Serializer):
    block_id = serializers.UUIDField()
    room_no = serializers.CharField(max_length=50)
    capacity = serializers.IntegerField(min_value=1, default=2)
```

- [ ] **Step 4: Add the views**

In `services/hostel-service/hostel/views.py`, add imports:

```python
from hostel.models import Block
from hostel.serializers import (
    BlockCreateSerializer,
    BlockSerializer,
    RoomCreateSerializer,
)
from rest_framework.generics import ListCreateAPIView
```

Add the views:

```python
class BlockListCreateView(ListCreateAPIView):
    """GET lists blocks (tenant-scoped, paginated); POST creates one.

    Admin-only: this is hostel setup, not a warden's day-to-day workflow.
    """

    permission_classes = [role_required("admin")]

    def get_queryset(self):
        return Block.objects.all().order_by("name")

    def get_serializer_class(self):
        return BlockCreateSerializer if self.request.method == "POST" else BlockSerializer

    def post(self, request):
        serializer = BlockCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid block payload.", errors=serializer.errors, status=400)

        try:
            warden = resolve_user_by_email(
                serializer.validated_data["warden_email"], request.META.get("HTTP_AUTHORIZATION")
            )
        except LookupFailed as exc:
            return fail(str(exc), status=400 if exc.reason == "not_found" else 502)

        block = Block.objects.create(
            tenant_id=get_current_tenant(),
            name=serializer.validated_data["name"],
            gender_type=serializer.validated_data["gender_type"],
            warden_id=warden["id"],
        )
        return ok(BlockSerializer(block).data, message="Block created.", status=201)


class RoomListCreateView(ListCreateAPIView):
    """GET lists ALL rooms (tenant-scoped, paginated) for management — distinct
    from AvailableRoomsView, which filters to open rooms for the allocation
    picker. POST creates a room; admin or warden may do this."""

    permission_classes = [role_required("admin", "warden")]

    def get_queryset(self):
        return Room.objects.all().order_by("block__name", "room_no")

    def get_serializer_class(self):
        return RoomCreateSerializer if self.request.method == "POST" else RoomSerializer

    def post(self, request):
        serializer = RoomCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return fail("Invalid room payload.", errors=serializer.errors, status=400)

        block = get_object_or_404(Block.objects.all(), id=serializer.validated_data["block_id"])
        room = Room.objects.create(
            tenant_id=get_current_tenant(),
            block=block,
            room_no=serializer.validated_data["room_no"],
            capacity=serializer.validated_data["capacity"],
        )
        return ok(RoomSerializer(room).data, message="Room created.", status=201)
```

Since `get_object_or_404` was removed from the top-level imports in Task 3's cleanup, re-add it:

```python
from django.shortcuts import get_object_or_404
```

- [ ] **Step 5: Wire the URLs**

In `services/hostel-service/hostel/urls.py`, final version:

```python
"""Hostel endpoints: allocate, rooms, blocks, allocations, bulk import,
import logs. Included under /api/v1/hostel/ from config.urls.
"""

from django.urls import path
from hostel.views import (
    AllocateBulkView,
    AllocateView,
    AllocationImportLogDetailView,
    AllocationImportLogListView,
    AllocationListView,
    AvailableRoomsView,
    BlockListCreateView,
    RoomListCreateView,
)

urlpatterns = [
    path("allocate", AllocateView.as_view(), name="allocate"),
    path("allocate/bulk", AllocateBulkView.as_view(), name="allocate-bulk"),
    path("rooms/available", AvailableRoomsView.as_view(), name="rooms-available"),
    path("rooms", RoomListCreateView.as_view(), name="room-list-create"),
    path("blocks", BlockListCreateView.as_view(), name="block-list-create"),
    path("allocations", AllocationListView.as_view(), name="allocation-list"),
    path("allocations/import-logs", AllocationImportLogListView.as_view(), name="allocation-import-log-list"),
    path(
        "allocations/import-logs/<uuid:pk>",
        AllocationImportLogDetailView.as_view(),
        name="allocation-import-log-detail",
    ),
]
```

- [ ] **Step 6: Run to verify pass**

Run: `cd services/hostel-service && pytest hostel/tests/test_blocks_rooms.py -v`
Expected: PASS (9 passed).

- [ ] **Step 7: Run the full suite**

Run: `cd services/hostel-service && pytest -q`
Expected: all tests pass, including `test_available_rooms_lists_only_rooms_with_capacity_tenant_scoped` (the added `block_name` field doesn't break its `id`-only assertions).

- [ ] **Step 8: Commit**

```bash
git add services/hostel-service/hostel/serializers.py services/hostel-service/hostel/views.py services/hostel-service/hostel/urls.py services/hostel-service/hostel/tests/test_blocks_rooms.py
git commit -m "feat(hostel): add block/room create and list endpoints"
```

---

## Task 9: frontend — `api.upload` multipart helper

**Files:**
- Modify: `frontend/su-erp-web/src/lib/api.ts`
- Test: `frontend/su-erp-web/src/lib/api.test.ts` (new)

**Interfaces:**
- Produces: `api.upload<T>(path: string, file: File, fieldName?: string) -> Promise<T>`. Consumed by Task 12 (`BulkAllocationImport`).

- [ ] **Step 1: Write the failing test**

Create `frontend/su-erp-web/src/lib/api.test.ts`:

```ts
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

import { api, ApiError } from "@/lib/api";
import { setToken } from "@/lib/auth";

describe("api.upload", () => {
  beforeEach(() => {
    window.localStorage.clear();
    setToken("tok");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts a file as multipart/form-data and unwraps the envelope", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      json: async () => ({ success: true, data: { batch_id: "b1" }, message: "ok", errors: null }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["a,b\n1,2"], "import.csv", { type: "text/csv" });
    const result = await api.upload<{ batch_id: string }>("/api/v1/hostel/allocate/bulk", file);

    expect(result).toEqual({ batch_id: "b1" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/api/v1/hostel/allocate/bulk");
    expect(init.method).toBe("POST");
    expect(init.headers["Authorization"]).toBe("Bearer tok");
    expect(init.headers["Content-Type"]).toBeUndefined();
    expect(init.body).toBeInstanceOf(FormData);
  });

  it("throws ApiError when the envelope reports failure", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      json: async () => ({ success: false, data: null, message: "Bad file.", errors: null }),
      status: 400,
    });
    vi.stubGlobal("fetch", fetchMock);

    const file = new File(["x"], "import.csv");
    await expect(api.upload("/api/v1/hostel/allocate/bulk", file)).rejects.toThrow(ApiError);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend/su-erp-web && npx vitest run src/lib/api.test.ts`
Expected: FAIL — `api.upload is not a function`.

- [ ] **Step 3: Refactor `api.ts` to add `apiUpload`, sharing envelope-unwrap logic**

Replace the full content of `frontend/su-erp-web/src/lib/api.ts`:

```ts
// Gateway API client for SU-ERP.
//
// Every backend service is reached through the gateway. This client attaches
// the bearer token, sends/parses JSON, and unwraps the standard response
// envelope: { success, data, message, errors }.

import { getToken } from "@/lib/auth";

const DEFAULT_GATEWAY_URL = "http://localhost:8080";

/** Standard response envelope returned by all gateway-fronted services. */
export interface ApiEnvelope<T = unknown> {
  success: boolean;
  data: T;
  message: string;
  errors: unknown;
}

/** Error thrown when the envelope reports failure or a transport error occurs. */
export class ApiError extends Error {
  readonly status: number | null;
  readonly errors: unknown;

  constructor(message: string, status: number | null = null, errors: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errors = errors;
  }
}

/** Gateway base URL from env, without a trailing slash. */
function gatewayBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_GATEWAY_URL || DEFAULT_GATEWAY_URL;
  return url.replace(/\/+$/, "");
}

function buildUrl(path: string): string {
  return `${gatewayBaseUrl()}${path.startsWith("/") ? path : `/${path}`}`;
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

/** Fetch + parse the standard envelope, throwing ApiError on transport or envelope failure. */
async function unwrap<T>(
  fetchCall: () => Promise<Response>,
  method: string,
  path: string,
): Promise<T> {
  let response: Response;
  try {
    response = await fetchCall();
  } catch (cause) {
    const detail = cause instanceof Error ? cause.message : String(cause);
    throw new ApiError(`Network error calling ${method} ${path}: ${detail}`);
  }

  let envelope: ApiEnvelope<T>;
  try {
    envelope = (await response.json()) as ApiEnvelope<T>;
  } catch {
    throw new ApiError(
      `Invalid response from ${method} ${path} (status ${response.status})`,
      response.status,
    );
  }

  if (!envelope || envelope.success !== true) {
    const message = envelope?.message || `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status, envelope?.errors ?? null);
  }

  return envelope.data;
}

/**
 * Call the gateway and unwrap the response envelope.
 *
 * - `method`: HTTP method (GET, POST, ...).
 * - `path`: path beginning with "/" (e.g. "/api/v1/auth/login").
 * - `body`: optional JSON-serializable payload.
 */
export async function apiCall<T = unknown>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const url = buildUrl(path);
  const headers = authHeaders();
  const init: RequestInit = { method: method.toUpperCase(), headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  return unwrap<T>(() => fetch(url, init), method, path);
}

/**
 * Upload a file as multipart/form-data and unwrap the response envelope.
 * Distinct from apiCall: the body must NOT be JSON-serialized, and
 * Content-Type must be left unset so the browser sets the multipart
 * boundary itself.
 */
export async function apiUpload<T = unknown>(
  path: string,
  file: File,
  fieldName = "file",
): Promise<T> {
  const url = buildUrl(path);
  const headers = authHeaders();
  const formData = new FormData();
  formData.append(fieldName, file);

  return unwrap<T>(() => fetch(url, { method: "POST", headers, body: formData }), "POST", path);
}

/** Convenience wrappers around apiCall/apiUpload. */
export const api = {
  get: <T = unknown>(path: string) => apiCall<T>("GET", path),
  post: <T = unknown>(path: string, body?: unknown) => apiCall<T>("POST", path, body),
  put: <T = unknown>(path: string, body?: unknown) => apiCall<T>("PUT", path, body),
  patch: <T = unknown>(path: string, body?: unknown) => apiCall<T>("PATCH", path, body),
  delete: <T = unknown>(path: string) => apiCall<T>("DELETE", path),
  upload: <T = unknown>(path: string, file: File, fieldName?: string) =>
    apiUpload<T>(path, file, fieldName),
};
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend/su-erp-web && npx vitest run src/lib/api.test.ts`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full frontend suite (no regressions from the refactor)**

Run: `cd frontend/su-erp-web && npm test`
Expected: all existing tests still pass (the refactor preserves `apiCall`'s exact behavior).

- [ ] **Step 6: Commit**

```bash
git add frontend/su-erp-web/src/lib/api.ts frontend/su-erp-web/src/lib/api.test.ts
git commit -m "feat(frontend): add multipart upload helper to the api client"
```

---

## Task 10: frontend — warden `CreateAllocation`: room picker + student email

**Files:**
- Modify: `frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx`
- Modify: `frontend/su-erp-web/src/app/(dashboard)/warden/warden.test.tsx`

**Interfaces:**
- Consumes: `GET /api/v1/hostel/rooms/available` (now returns `block_name` per Task 8).
- Produces: `CreateAllocation` now takes a `rooms: Room[]` prop instead of managing its own text inputs; posts `{room_id, student_email}`.

- [ ] **Step 1: Update the existing test**

In `frontend/su-erp-web/src/app/(dashboard)/warden/warden.test.tsx`, update the `get` mock in the "creates a hostel allocation" test to also serve rooms, and change the interaction to use the room `<select>` and an email field. Replace that whole `it` block:

```tsx
  it("creates a hostel allocation", async () => {
    get.mockImplementation((path: string) => {
      if (path.includes("/hostel/rooms/available")) {
        return Promise.resolve({
          items: [{ id: "rm-1", block_name: "Block A", room_no: "101", capacity: 2, occupied_count: 0 }],
          total: 1,
        });
      }
      return Promise.resolve({ items: [], total: 0 });
    });
    post.mockResolvedValue({ id: "a-2", status: "pending", room_id: "rm-1", student_id: "stu-1" });

    render(<WardenDashboard />);
    await screen.findByText("No pending allocations.");

    fireEvent.change(screen.getByLabelText("Room"), { target: { value: "rm-1" } });
    fireEvent.change(screen.getByLabelText("Student email"), { target: { value: "student@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Create allocation" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/hostel/allocate", {
        room_id: "rm-1",
        student_email: "student@example.com",
      }),
    );
    expect(await screen.findByText("Allocation created.")).toBeInTheDocument();
  });
```

Also update the two earlier tests' `get.mockImplementation`/`get.mockResolvedValue` calls so they don't break now that `WardenContent` fetches a third resource (`rooms/available`) — since those mocks already fall through to `Promise.resolve([])`/`{items: [], total: 0}` for unmatched/default paths, no change is needed there (double check: the first test's `get.mockImplementation` has an explicit `return Promise.resolve([]);` fallback — that covers the new rooms call fine).

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend/su-erp-web && npx vitest run src/app/\(dashboard\)/warden/warden.test.tsx`
Expected: FAIL — no `"Room"` or `"Student email"` labeled controls yet (still "Room ID"/"Student ID" text inputs).

- [ ] **Step 3: Update `warden/page.tsx`**

Add `Select` and `Room` interface, wire a `rooms` loader in `WardenContent`, and rewrite `CreateAllocation`. Apply these changes to `frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx`:

Add to the imports:

```tsx
import { Select } from "@/components/ui/Select";
```

Add the `Room` interface near `Allocation`/`Grievance`:

```tsx
interface Room {
  id: string;
  block_name: string;
  room_no: string;
  capacity: number;
  occupied_count: number;
}
```

In `WardenContent`, add a rooms loader alongside `loadAllocations`/`loadGrievances`:

```tsx
  const [rooms, setRooms] = useState<Room[]>([]);
  const [roomsLoading, setRoomsLoading] = useState(true);

  const loadRooms = useCallback(async () => {
    setRoomsLoading(true);
    try {
      const data = await api.get("/api/v1/hostel/rooms/available");
      setRooms(listItems<Room>(data));
    } finally {
      setRoomsLoading(false);
    }
  }, []);
```

Update the `useEffect` to also call it:

```tsx
  useEffect(() => {
    void loadAllocations();
    void loadGrievances();
    void loadRooms();
  }, [loadAllocations, loadGrievances, loadRooms]);
```

Update the `onCreated` callback passed to `CreateAllocation` so both allocations and the room list refresh (an allocation changes `occupied_count`), and pass `rooms`:

```tsx
      <CreateAllocation
        rooms={rooms}
        onCreated={() => {
          void loadAllocations();
          void loadRooms();
        }}
      />
```

Replace the whole `CreateAllocation` function:

```tsx
function CreateAllocation({ rooms, onCreated }: { rooms: Room[]; onCreated: () => void }) {
  const [roomId, setRoomId] = useState("");
  const [studentEmail, setStudentEmail] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post("/api/v1/hostel/allocate", {
        room_id: roomId,
        student_email: studentEmail,
      });
      setOk("Allocation created.");
      setRoomId("");
      setStudentEmail("");
      onCreated();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Create allocation" />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Room" htmlFor="alloc-room">
              <Select
                id="alloc-room"
                value={roomId}
                onChange={(e) => setRoomId(e.target.value)}
                required
              >
                <option value="" disabled>
                  Select a room
                </option>
                {rooms.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.block_name}/{r.room_no} ({r.occupied_count}/{r.capacity})
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Student email" htmlFor="alloc-student">
              <Input
                id="alloc-student"
                type="email"
                value={studentEmail}
                onChange={(e) => setStudentEmail(e.target.value)}
                required
              />
            </Field>
          </div>
          {error && <Alert tone="error">{error}</Alert>}
          {ok && <Alert tone="success">{ok}</Alert>}
          <Button type="submit" loading={pending}>
            Create allocation
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend/su-erp-web && npx vitest run src/app/\(dashboard\)/warden/warden.test.tsx`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/su-erp-web/src/app/"(dashboard)"/warden/page.tsx frontend/su-erp-web/src/app/"(dashboard)"/warden/warden.test.tsx
git commit -m "feat(frontend): allocate by student email with a room picker"
```

---

## Task 11: frontend — `BulkAllocationImport` + sample CSV

**Files:**
- Modify: `frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx`
- Modify: `frontend/su-erp-web/src/app/(dashboard)/warden/warden.test.tsx`
- Create: `frontend/su-erp-web/public/sample-allocation-import.csv`

**Interfaces:**
- Consumes: `api.upload` (Task 9).
- Produces: `BulkAllocationImport` component rendered in `WardenContent`, posting to `/api/v1/hostel/allocate/bulk`.

- [ ] **Step 1: Create the sample CSV**

Create `frontend/su-erp-web/public/sample-allocation-import.csv`:

```
room_id,student_email
00000000-0000-0000-0000-000000000000,student@example.com
```

- [ ] **Step 2: Write the failing test**

In `frontend/su-erp-web/src/app/(dashboard)/warden/warden.test.tsx`, add `upload` to the `@/lib/api` mock:

```tsx
const get = vi.fn();
const post = vi.fn();
const upload = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      get: (...args: unknown[]) => get(...args),
      post: (...args: unknown[]) => post(...args),
      upload: (...args: unknown[]) => upload(...args),
    },
  };
});
```

Add `upload.mockReset();` to the `beforeEach`. Add a new test:

```tsx
  it("uploads a bulk allocation file and shows the summary", async () => {
    get.mockResolvedValue({ items: [], total: 0 });
    upload.mockResolvedValue({ batch_id: "b1", total_rows: 3, success_count: 2, fail_count: 1 });

    render(<WardenDashboard />);
    await screen.findByText("No pending allocations.");

    const file = new File(["room_id,student_email\n"], "import.csv", { type: "text/csv" });
    const input = screen.getByLabelText("File") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() =>
      expect(upload).toHaveBeenCalledWith("/api/v1/hostel/allocate/bulk", file),
    );
    expect(
      await screen.findByText(/2 succeeded, 1 failed out of 3/),
    ).toBeInTheDocument();
  });
```

- [ ] **Step 3: Run to verify failure**

Run: `cd frontend/su-erp-web && npx vitest run src/app/\(dashboard\)/warden/warden.test.tsx`
Expected: FAIL — no "File"-labeled control or "Upload" button exists.

- [ ] **Step 4: Add `BulkAllocationImport` to `warden/page.tsx`**

Add the component (after `CreateAllocation`):

```tsx
interface BulkImportSummary {
  batch_id: string;
  total_rows: number;
  success_count: number;
  fail_count: number;
}

function BulkAllocationImport({ onImported }: { onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<BulkImportSummary | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setPending(true);
    setError(null);
    setSummary(null);
    try {
      const result = await api.upload<BulkImportSummary>("/api/v1/hostel/allocate/bulk", file);
      setSummary(result);
      setFile(null);
      onImported();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Bulk allocate from CSV/XLSX" />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <a
            href="/sample-allocation-import.csv"
            download
            className="text-[13px] text-primary underline"
          >
            Download sample CSV
          </a>
          <Field label="File" htmlFor="bulk-file">
            <input
              id="bulk-file"
              type="file"
              accept=".csv,.xlsx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-ink"
              required
            />
          </Field>
          {error && <Alert tone="error">{error}</Alert>}
          {summary && (
            <Alert tone={summary.fail_count > 0 ? "info" : "success"}>
              {summary.success_count} succeeded, {summary.fail_count} failed out of{" "}
              {summary.total_rows}. See Import Logs below for details.
            </Alert>
          )}
          <Button type="submit" loading={pending} disabled={!file}>
            Upload
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
```

Render it in `WardenContent`, right after `<CreateAllocation ... />`:

```tsx
      <BulkAllocationImport
        onImported={() => {
          void loadAllocations();
          void loadRooms();
        }}
      />
```

- [ ] **Step 5: Run to verify pass**

Run: `cd frontend/su-erp-web && npx vitest run src/app/\(dashboard\)/warden/warden.test.tsx`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add frontend/su-erp-web/src/app/"(dashboard)"/warden/page.tsx frontend/su-erp-web/src/app/"(dashboard)"/warden/warden.test.tsx frontend/su-erp-web/public/sample-allocation-import.csv
git commit -m "feat(frontend): add bulk CSV/XLSX allocation upload"
```

---

## Task 12: frontend — Import Logs panel

**Files:**
- Modify: `frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx`
- Modify: `frontend/su-erp-web/src/app/(dashboard)/warden/warden.test.tsx`

**Interfaces:**
- Consumes: `GET /api/v1/hostel/allocations/import-logs`, `GET /api/v1/hostel/allocations/import-logs/<id>` (Task 7).

- [ ] **Step 1: Write the failing test**

Add to `frontend/su-erp-web/src/app/(dashboard)/warden/warden.test.tsx`:

```tsx
  it("shows import logs and drills into a batch's rows", async () => {
    get.mockImplementation((path: string) => {
      if (path.includes("/import-logs/batch-1")) {
        return Promise.resolve({
          id: "batch-1",
          filename: "import.csv",
          total_rows: 1,
          success_count: 0,
          fail_count: 1,
          created_at: "2026-01-01T00:00:00Z",
          rows: [
            {
              row_number: 1,
              room_id_raw: "rm-9",
              student_email_raw: "bad@example.com",
              status: "failed",
              error_message: "No user found with email bad@example.com.",
              allocation_id: null,
            },
          ],
        });
      }
      if (path.includes("/import-logs")) {
        return Promise.resolve({
          items: [
            {
              id: "batch-1",
              filename: "import.csv",
              total_rows: 1,
              success_count: 0,
              fail_count: 1,
              created_at: "2026-01-01T00:00:00Z",
            },
          ],
          total: 1,
        });
      }
      return Promise.resolve({ items: [], total: 0 });
    });

    render(<WardenDashboard />);

    expect(await screen.findByText("import.csv")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View" }));

    expect(
      await screen.findByText("No user found with email bad@example.com."),
    ).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend/su-erp-web && npx vitest run src/app/\(dashboard\)/warden/warden.test.tsx`
Expected: FAIL — no Import Logs panel rendered.

- [ ] **Step 3: Add `ImportLogs` to `warden/page.tsx`**

Add the interfaces and component:

```tsx
interface ImportBatch {
  id: string;
  filename: string;
  total_rows: number;
  success_count: number;
  fail_count: number;
  created_at: string;
}

interface ImportRow {
  row_number: number;
  room_id_raw: string;
  student_email_raw: string;
  status: string;
  error_message: string;
  allocation_id: string | null;
}

function ImportLogs() {
  const [batches, setBatches] = useState<ImportBatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [rows, setRows] = useState<ImportRow[]>([]);
  const [rowsLoading, setRowsLoading] = useState(false);

  const loadBatches = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get("/api/v1/hostel/allocations/import-logs");
      setBatches(listItems<ImportBatch>(data));
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBatches();
  }, [loadBatches]);

  async function viewBatch(id: string) {
    setSelectedId(id);
    setRowsLoading(true);
    try {
      const data = await api.get<{ rows: ImportRow[] }>(`/api/v1/hostel/allocations/import-logs/${id}`);
      setRows(data.rows ?? []);
    } finally {
      setRowsLoading(false);
    }
  }

  return (
    <DataPanel
      title="Import logs"
      loading={loading}
      error={error}
      isEmpty={batches.length === 0}
      emptyLabel="No bulk imports yet."
    >
      <Table>
        <THead>
          <HeaderRow>
            <TH>File</TH>
            <TH>Uploaded</TH>
            <TH>Success</TH>
            <TH>Failed</TH>
            <TH />
          </HeaderRow>
        </THead>
        <TBody>
          {batches.map((b) => (
            <Row key={b.id}>
              <TD className="font-medium">{b.filename}</TD>
              <TD className="text-muted">{new Date(b.created_at).toLocaleString()}</TD>
              <TD>{b.success_count}</TD>
              <TD>{b.fail_count}</TD>
              <TD>
                <Button variant="ghost" size="sm" onClick={() => viewBatch(b.id)}>
                  View
                </Button>
              </TD>
            </Row>
          ))}
        </TBody>
      </Table>

      {selectedId &&
        (rowsLoading ? (
          <p className="mt-4 text-[13px] text-muted">Loading…</p>
        ) : (
          <Table>
            <THead>
              <HeaderRow>
                <TH>Row</TH>
                <TH>Room ID</TH>
                <TH>Student email</TH>
                <TH>Status</TH>
                <TH>Error</TH>
              </HeaderRow>
            </THead>
            <TBody>
              {rows.map((r) => (
                <Row key={r.row_number}>
                  <TD>{r.row_number}</TD>
                  <TD className="font-mono text-[12px]">{r.room_id_raw}</TD>
                  <TD>{r.student_email_raw}</TD>
                  <TD>
                    <StatusPill status={r.status} />
                  </TD>
                  <TD className="text-muted">{r.error_message}</TD>
                </Row>
              ))}
            </TBody>
          </Table>
        ))}
    </DataPanel>
  );
}
```

Render `<ImportLogs />` in `WardenContent`'s JSX, after the `BulkAllocationImport` block.

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend/su-erp-web && npx vitest run src/app/\(dashboard\)/warden/warden.test.tsx`
Expected: PASS (5 passed).

- [ ] **Step 5: Run the full frontend suite**

Run: `cd frontend/su-erp-web && npm test`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/su-erp-web/src/app/"(dashboard)"/warden/page.tsx frontend/su-erp-web/src/app/"(dashboard)"/warden/warden.test.tsx
git commit -m "feat(frontend): add import logs panel to warden dashboard"
```

---

## Task 13: frontend — admin "Hostel Setup" (blocks + rooms)

**Files:**
- Modify: `frontend/su-erp-web/src/app/(dashboard)/admin/page.tsx`
- Modify: `frontend/su-erp-web/src/app/(dashboard)/admin/admin.test.tsx`

**Interfaces:**
- Consumes: `POST/GET /api/v1/hostel/blocks`, `POST/GET /api/v1/hostel/rooms` (Task 8).

- [ ] **Step 1: Write the failing tests**

Add to `frontend/su-erp-web/src/app/(dashboard)/admin/admin.test.tsx`, extending `defaultGet` to serve blocks/rooms and adding two new tests:

```tsx
function defaultGet(path: string) {
  if (path.includes("/auth/institution")) return Promise.resolve(INSTITUTION);
  if (path.includes("/auth/users")) return Promise.resolve(userList());
  if (path.includes("/finance/invoices")) return Promise.resolve({ items: [{}], total: 156 });
  if (path.includes("/hostel/allocations")) return Promise.resolve({ items: [{}], total: 30 });
  if (path.includes("/grievance")) return Promise.resolve({ items: [{}], total: 7 });
  if (path.includes("/hostel/blocks")) {
    return Promise.resolve({ items: [{ id: "blk-1", name: "Block A", gender_type: "M", warden_id: "w1" }], total: 1 });
  }
  if (path.includes("/hostel/rooms")) {
    return Promise.resolve({
      items: [{ id: "rm-1", block_name: "Block A", room_no: "101", capacity: 2, occupied_count: 1 }],
      total: 1,
    });
  }
  return Promise.resolve({ items: [], total: 0 });
}
```

```tsx
  it("renders hostel blocks and rooms", async () => {
    get.mockImplementation(defaultGet);

    render(<AdminDashboard />);

    expect(await screen.findByText("Block A")).toBeInTheDocument();
    expect(await screen.findByText("101")).toBeInTheDocument();
  });

  it("creates a block by warden email", async () => {
    get.mockImplementation(defaultGet);
    post.mockResolvedValue({ id: "blk-2", name: "Block B", gender_type: "F", warden_id: "w2" });

    render(<AdminDashboard />);
    await screen.findByText("Block A");

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Block B" } });
    fireEvent.change(screen.getByLabelText("Gender type"), { target: { value: "F" } });
    fireEvent.change(screen.getByLabelText("Warden email"), { target: { value: "warden@acme.edu" } });
    fireEvent.click(screen.getByRole("button", { name: "Create block" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/hostel/blocks", {
        name: "Block B",
        gender_type: "F",
        warden_email: "warden@acme.edu",
      }),
    );
    expect(await screen.findByText("Block created.")).toBeInTheDocument();
  });

  it("creates a room under a block", async () => {
    get.mockImplementation(defaultGet);
    post.mockResolvedValue({ id: "rm-2", block_name: "Block A", room_no: "202", capacity: 2, occupied_count: 0 });

    render(<AdminDashboard />);
    await screen.findByText("Block A");

    fireEvent.change(screen.getByLabelText("Block"), { target: { value: "blk-1" } });
    fireEvent.change(screen.getByLabelText("Room number"), { target: { value: "202" } });
    fireEvent.change(screen.getByLabelText("Capacity"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Create room" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/hostel/rooms", {
        block_id: "blk-1",
        room_no: "202",
        capacity: 2,
      }),
    );
    expect(await screen.findByText("Room created.")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend/su-erp-web && npx vitest run src/app/\(dashboard\)/admin/admin.test.tsx`
Expected: FAIL — no Hostel Setup section, "Name"/"Gender type"/"Warden email"/"Block"/"Room number"/"Capacity" labels don't exist yet in this page (note: "Capacity" and "Name" could collide with other labels if any existed — there are none currently on this page, so this is safe).

- [ ] **Step 3: Add `HostelSetup`, `CreateBlock`, `CreateRoom` to `admin/page.tsx`**

Add interfaces near the top (after `User`):

```tsx
interface Block {
  id: string;
  name: string;
  gender_type: string;
  warden_id: string;
}

interface HostelRoom {
  id: string;
  block_name: string;
  room_no: string;
  capacity: number;
  occupied_count: number;
}
```

Render `<HostelSetup />` in `AdminContent`'s JSX, after the "Add user" `Card`:

```tsx
      <HostelSetup />
```

Add the components at the end of the file, before `export default function AdminDashboard`:

```tsx
function HostelSetup() {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [blocksLoading, setBlocksLoading] = useState(true);
  const [blocksError, setBlocksError] = useState<string | null>(null);

  const [rooms, setRooms] = useState<HostelRoom[]>([]);
  const [roomsLoading, setRoomsLoading] = useState(true);
  const [roomsError, setRoomsError] = useState<string | null>(null);

  const loadBlocks = useCallback(async () => {
    setBlocksLoading(true);
    setBlocksError(null);
    try {
      const data = await api.get("/api/v1/hostel/blocks");
      setBlocks(listItems<Block>(data));
    } catch (e) {
      setBlocksError(errMsg(e));
    } finally {
      setBlocksLoading(false);
    }
  }, []);

  const loadRooms = useCallback(async () => {
    setRoomsLoading(true);
    setRoomsError(null);
    try {
      const data = await api.get("/api/v1/hostel/rooms");
      setRooms(listItems<HostelRoom>(data));
    } catch (e) {
      setRoomsError(errMsg(e));
    } finally {
      setRoomsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadBlocks();
    void loadRooms();
  }, [loadBlocks, loadRooms]);

  return (
    <div className="space-y-6">
      <CreateBlock onCreated={loadBlocks} />
      <DataPanel
        title="Blocks"
        loading={blocksLoading}
        error={blocksError}
        isEmpty={blocks.length === 0}
        emptyLabel="No blocks yet. Add one below."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Name</TH>
              <TH>Gender</TH>
              <TH>Warden</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {blocks.map((b) => (
              <Row key={b.id}>
                <TD className="font-medium">{b.name}</TD>
                <TD className="text-muted">{b.gender_type}</TD>
                <TD className="font-mono text-[12px]">{b.warden_id}</TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>

      <CreateRoom blocks={blocks} onCreated={loadRooms} />
      <DataPanel
        title="Rooms"
        loading={roomsLoading}
        error={roomsError}
        isEmpty={rooms.length === 0}
        emptyLabel="No rooms yet. Add one below."
      >
        <Table>
          <THead>
            <HeaderRow>
              <TH>Block</TH>
              <TH>Room no.</TH>
              <TH>Occupancy</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {rooms.map((r) => (
              <Row key={r.id}>
                <TD className="font-medium">{r.block_name}</TD>
                <TD>{r.room_no}</TD>
                <TD className="text-muted">
                  {r.occupied_count}/{r.capacity}
                </TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </DataPanel>
    </div>
  );
}

function CreateBlock({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [genderType, setGenderType] = useState<"M" | "F">("M");
  const [wardenEmail, setWardenEmail] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post("/api/v1/hostel/blocks", {
        name,
        gender_type: genderType,
        warden_email: wardenEmail,
      });
      setOk("Block created.");
      setName("");
      setWardenEmail("");
      onCreated();
    } catch (err) {
      setError(fieldErrorMessage(err) ?? errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Create block" />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Name" htmlFor="block-name">
              <Input id="block-name" value={name} onChange={(e) => setName(e.target.value)} required />
            </Field>
            <Field label="Gender type" htmlFor="block-gender">
              <Select
                id="block-gender"
                value={genderType}
                onChange={(e) => setGenderType(e.target.value as "M" | "F")}
              >
                <option value="M">Male</option>
                <option value="F">Female</option>
              </Select>
            </Field>
            <Field label="Warden email" htmlFor="block-warden">
              <Input
                id="block-warden"
                type="email"
                value={wardenEmail}
                onChange={(e) => setWardenEmail(e.target.value)}
                required
              />
            </Field>
          </div>
          {error && <Alert tone="error">{error}</Alert>}
          {ok && <Alert tone="success">{ok}</Alert>}
          <Button type="submit" loading={pending}>
            Create block
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}

function CreateRoom({ blocks, onCreated }: { blocks: Block[]; onCreated: () => void }) {
  const [blockId, setBlockId] = useState("");
  const [roomNo, setRoomNo] = useState("");
  const [capacity, setCapacity] = useState("2");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setPending(true);
    setError(null);
    setOk(null);
    try {
      await api.post("/api/v1/hostel/rooms", {
        block_id: blockId,
        room_no: roomNo,
        capacity: Number(capacity),
      });
      setOk("Room created.");
      setRoomNo("");
      onCreated();
    } catch (err) {
      setError(fieldErrorMessage(err) ?? errMsg(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Create room" />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Block" htmlFor="room-block">
              <Select id="room-block" value={blockId} onChange={(e) => setBlockId(e.target.value)} required>
                <option value="" disabled>
                  Select a block
                </option>
                {blocks.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Room number" htmlFor="room-no">
              <Input id="room-no" value={roomNo} onChange={(e) => setRoomNo(e.target.value)} required />
            </Field>
            <Field label="Capacity" htmlFor="room-capacity">
              <Input
                id="room-capacity"
                type="number"
                min={1}
                value={capacity}
                onChange={(e) => setCapacity(e.target.value)}
                required
              />
            </Field>
          </div>
          {error && <Alert tone="error">{error}</Alert>}
          {ok && <Alert tone="success">{ok}</Alert>}
          <Button type="submit" loading={pending}>
            Create room
          </Button>
        </form>
      </CardBody>
    </Card>
  );
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend/su-erp-web && npx vitest run src/app/\(dashboard\)/admin/admin.test.tsx`
Expected: PASS (7 passed).

- [ ] **Step 5: Run the full frontend suite**

Run: `cd frontend/su-erp-web && npm test`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/su-erp-web/src/app/"(dashboard)"/admin/page.tsx frontend/su-erp-web/src/app/"(dashboard)"/admin/admin.test.tsx
git commit -m "feat(frontend): add hostel block/room setup to admin dashboard"
```

---

## Task 14: End-to-end sanity check

Not a code task — a manual verification pass before calling the feature done, per the project's `verify` skill convention. No committable changes are expected here unless a bug surfaces (in which case, fix it under this task and commit the fix).

- [ ] **Step 1: Run every backend suite**

```bash
cd services/auth-service && pytest -q
cd services/hostel-service && pytest -q
```
Expected: all pass.

- [ ] **Step 2: Run the frontend suite**

```bash
cd frontend/su-erp-web && npm test
```
Expected: all pass.

- [ ] **Step 3: Boot the stack and walk the golden path**

```bash
cd infra && docker compose up -d --build gateway auth-service hostel-service frontend postgres pgbouncer redis rabbitmq
```

As an admin: log in, create a Block (with a real warden's email), create a Room under it. As a warden: log in, confirm the new room appears in the "Create allocation" dropdown, allocate it by a real student's email, confirm it appears in "Pending hostel allocations". Download the sample CSV, fill in a real room UUID and student email, upload it via "Bulk allocate from CSV/XLSX", confirm the summary and the Import Logs entry (including drilling into row detail) both reflect the result.

- [ ] **Step 4: Tear down**

```bash
cd infra && docker compose down
```
