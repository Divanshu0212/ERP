# Allocation by student email + bulk CSV/XLSX import + hostel setup

Date: 2026-07-04
Status: Approved, ready for planning

## Problem

The warden's "create allocation" form requires typing raw `room_id` and
`student_id` UUIDs. There is no way to discover either UUID from the
frontend, no room/block creation UI or endpoint (rooms only exist via
backend fixtures/migrations), and no bulk way to allocate many students
at once. This spec:

1. Switches student identification from `student_id` to `student_email`.
2. Adds a room picker (dropdown) to replace manual room UUID entry.
3. Adds room/block creation (backend + admin UI), since without it the
   feature has no real rooms to allocate against outside of fixtures.
4. Adds bulk allocation via CSV/XLSX upload with a persisted per-batch,
   per-row success/fail log surfaced in a warden-facing "Import Logs" tab.

## Architecture

DB-per-service is preserved; no new cross-service FKs are introduced.
`student_id`/`warden_id` remain bare UUIDs in hostel-service. Investigation
of the existing codebase (`services/finance-service/billing/models.py:38-40`,
`services/finance-service/billing/consumers.py:52-80`,
`services/notification-service/notify/consumers.py:52-57`, and the existing
admin "Create invoice" form at `frontend/su-erp-web/src/app/(dashboard)/admin/page.tsx:266-274`)
confirms that **every `student_id` field in this platform is actually the
auth-service `User.id`**, not a separate student-service row id — the
model docstrings calling it "student-service's Student table" are
inaccurate. This makes sense operationally: `notification-service` writes
`Notification.user_id` directly from a `student_id` payload, and the only
id space that can mean anything to a JWT's `sub` claim (the currently
logged-in user's own id) is the auth `User.id`. `student-service`'s
`StudentProfile.id` is never used as this identifier anywhere in the
codebase.

Consequently, email resolution is a **single-hop, single-service concern**:

- New `GET /accounts/users/by-email/?email=...` on auth-service, restricted
  to `warden`/`admin` roles, returns `{id, email, role}`. Used both to
  resolve a student's email to their `User.id` (for allocation) and a
  warden's email to their `User.id` (for Block creation) — one endpoint,
  two callers.
- hostel-service calls this endpoint synchronously through the gateway,
  forwarding the caller's existing bearer token, 5s timeout, no retries,
  no soft-fail — a lookup miss or timeout is a hard error back to the
  caller (single-create) or a per-row failure (bulk import), since
  allocation creation has real downstream consequences (invoice
  generation via the existing saga) and must not silently proceed with
  wrong/missing data.
- **No changes to student-service at all** — it has no role in identity
  resolution today and none is added.

This is the first synchronous inter-service HTTP call among the Django
services (previously all cross-service communication was async via the
outbox/inbox pattern in `suerp_common`). It is deliberately narrow: one
small helper local to hostel-service (`hostel/lookups.py`), not a new
shared library, since only hostel-service needs it today.

Bulk import runs **synchronously within the request** — one HTTP call
parses the file, creates each allocation in its own DB transaction, and
returns a summary. No async worker/queue. This matches expected load
(tens to low hundreds of rows per warden upload) and the project's
existing local-CPU-constraint guidance to avoid new infra for low-volume,
per-institution operations.

## Changes by service

### auth-service

- New `GET /accounts/users/by-email/?email=...` (`UserByEmailView`):
  looks up `User.objects.filter(tenant_id=request.user.tenant_id,
  email__iexact=email)`, returns `{id, email, role}`; restricted to
  `warden`/`admin` roles via the existing `role_required` decorator. 404
  on no match (envelope `fail(..., status=404)`).

### hostel-service

- New `hostel/lookups.py`: `resolve_user_by_email(email, auth_header) ->
  dict`, calling `f"{settings.GATEWAY_URL}/api/v1/auth/users/by-email/?email={email}"`
  with the forwarded bearer token, 5s timeout via `requests`. Raises a
  local `LookupFailed(reason: Literal["not_found", "unavailable"])`
  exception on 404 or any other non-2xx/timeout/connection error.
- `hostel/serializers.py`: `AllocateRequestSerializer.student_id` (UUID)
  → `student_email` (EmailField).
- `hostel/views.py`:
  - Extract the existing create-allocation body (lock room, check
    availability, create `Allocation`, increment `occupied_count`,
    publish `hostel.allocation.requested`, all in
    `transaction.atomic()`) out of `AllocateView.post` into a shared
    `create_allocation(room_id, student_id, tenant_id) -> Allocation`
    function in `hostel/services.py`, reused by both single and bulk
    create. Raises `RoomFullError`/`Room.DoesNotExist` on failure (both
    already-existing conditions, just relocated).
  - `AllocateView.post`: resolve `student_email` → `student_id` via
    `resolve_user_by_email`, then call `create_allocation`. A
    `LookupFailed("not_found")` returns 400; `LookupFailed("unavailable")`
    returns 502.
  - New `AllocateBulkView` (`POST /hostel/allocate/bulk`,
    `warden`/`admin` only, `MultiPartParser`): accepts one file field.
    Sniffs `.csv`/`.xlsx` by extension (415 on anything else). Parses
    rows expecting `room_id,student_email` columns (stdlib `csv` for CSV;
    `openpyxl` — new dependency — for XLSX). For each row: resolve email
    (memoized per-request dict, so a repeated email in the sheet costs
    one lookup), call `create_allocation` in its own try/except so one
    bad row doesn't abort the batch. Writes one `AllocationImportBatch`
    and one `AllocationImportRow` per input row. Returns `{batch_id,
    total_rows, success_count, fail_count}`.
  - New `AllocationImportLogListView` (`GET
    /hostel/allocations/import-logs`) and
    `AllocationImportLogDetailView` (`GET
    /hostel/allocations/import-logs/<id>`), `warden`/`admin` only.
  - New `BlockCreateView` (`POST /hostel/blocks`, admin only): body
    `{name, gender_type, warden_email}`, resolves warden email via
    `resolve_user_by_email`, creates `Block`.
  - New `BlockListView` (`GET /hostel/blocks`).
  - New `RoomCreateView` (`POST /hostel/rooms`, admin/warden): body
    `{block_id, room_no, capacity}`, creates `Room`.
  - New `RoomListView` (`GET /hostel/rooms`, full list for management —
    distinct from the existing `GET /hostel/rooms/available`, which
    stays scoped to open rooms for the allocation picker).
- `hostel/models.py`: two new models.
  - `AllocationImportBatch(TenantModel)`: `id`, `uploaded_by` (bare
    UUID), `filename`, `total_rows`, `success_count`, `fail_count`,
    `created_at`.
  - `AllocationImportRow(TenantModel)`: `batch` FK (`related_name=
    "rows"`), `row_number`, `room_id_raw` (text, as submitted),
    `student_email_raw`, `status` (`success`/`fail`), `error_message`
    (blank), `allocation` (nullable FK to `Allocation`).
- `config/settings.py`: add `GATEWAY_URL = env("GATEWAY_URL",
  default="http://gateway:8080")`.
- `requirements.txt`: add `openpyxl` (XLSX parsing) and `requests` (sync
  HTTP lookup).

### frontend (`frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx`)

- `CreateAllocation`: room `Input` → `Select` populated from `GET
  /hostel/rooms/available`, labeled `Block / RoomNo (occupied/capacity)`,
  value is the real `room_id`. `studentId` `Input` → `studentEmail`
  `Input` (`type="email"`). POST body: `{room_id, student_email}`.
- New `BulkAllocationImport` component: static "Download sample CSV" link
  (`public/sample-allocation-import.csv`, header `room_id,student_email`
  plus one example row) — no XLSX sample is needed since the CSV opens
  fine in Excel and can be re-saved as `.xlsx` if desired; file input
  accepting `.csv,.xlsx`; upload posts multipart to
  `/api/v1/hostel/allocate/bulk`; renders the returned summary inline
  with a link into the Import Logs tab for the new batch.
- New "Import Logs" tab/panel using the existing `DataPanel` + `Table`
  pattern: batch list (filename, uploaded_at, success/fail counts) from
  `GET /hostel/allocations/import-logs`; selecting a batch shows its
  row-level detail (room_id, email, status, error) from
  `GET /hostel/allocations/import-logs/<id>`.
- `src/lib/api.ts` gains a multipart upload helper (`apiUpload`) since
  the existing `apiCall` always JSON-serializes the body.

### frontend (`frontend/su-erp-web/src/app/(dashboard)/admin/page.tsx`)

- New "Hostel Setup" section:
  - Create Block form: name, gender_type select, warden email → `POST
    /hostel/blocks`; table listing existing blocks (`GET
    /hostel/blocks`).
  - Create Room form: block `Select` (from the blocks list above), room
    number, capacity → `POST /hostel/rooms`; table listing existing
    rooms (`GET /hostel/rooms`).

## Error handling

- Email lookup miss (student or warden): 400 surfaced verbatim to the
  caller — "No user found with email X" — both for single-create and
  per-row in bulk (where it becomes that row's `error_message`, not a
  batch-aborting error).
- Lookup timeout/gateway failure: 502 for single-create; for bulk, that
  row is marked failed with "Lookup service unavailable" and processing
  continues to the next row.
- Room unavailable (`is_available == False`) or room not found: existing
  behavior preserved (400/404 for single-create, per-row failure in
  bulk).
- Malformed file (wrong extension, missing columns, unreadable content):
  415/400 before any row processing begins, no batch is created.
- Partial batch failure is expected and not an error state — the
  response and log always report a mix of `success_count`/`fail_count`;
  there's no overall failure unless the file itself couldn't be parsed.

## Testing

- auth-service: new by-email endpoint tests (found, not-found,
  permission — student/faculty roles rejected, warden/admin allowed,
  cross-tenant lookup returns 404).
- hostel-service: `create_allocation` extraction covered by existing
  `test_allocate.py` (should require no behavior change, only a call-site
  move); new tests for `AllocateView` with email resolution (success,
  email-not-found -> 400, lookup-service-down -> 502, mocking
  `resolve_user_by_email`); `AllocateBulkView` tests covering all-success
  CSV, all-success XLSX, mixed success/fail, malformed file, wrong
  extension, missing columns; import-log list and detail view tests;
  block/room create + list view tests including role restrictions.
- frontend: extend `warden.test.tsx` for the room `Select` and email
  field; new tests for `BulkAllocationImport` (upload, summary render)
  and the Import Logs panel; admin page tests for the new Hostel Setup
  forms.

## Out of scope

- Async/queued bulk processing (deferred; current scale doesn't warrant
  it).
- A generic student directory/search UI (email replaces the need to see
  student UUIDs directly).
- Editing/deleting Blocks or Rooms (create + list only, matching the
  minimal need identified here).
- XLSX sample template (CSV sample suffices; XLSX upload is still
  supported for input).
- Any change to student-service (confirmed unnecessary — see
  Architecture).
