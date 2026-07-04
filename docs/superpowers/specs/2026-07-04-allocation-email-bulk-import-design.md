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

DB-per-service is preserved. `student_id`/`warden_id` remain bare UUIDs
in hostel-service (no cross-service FKs), matching existing conventions
documented in `services/hostel-service/hostel/models.py`. Email
resolution happens via:

- **Event replication**: auth-service's existing `user.registered`
  outbox event gains an `email` field in its payload. student-service
  gains its first inbox consumer, which denormalizes `email` onto
  `StudentProfile` for student-role users.
- **Synchronous lookup at write time**: hostel-service resolves
  `student_email` → `student_id` via a new `GET /students/by-email/`
  endpoint on student-service, and `warden_email` → `user_id` via a new
  `GET /accounts/users/by-email/` endpoint on auth-service. Both calls go
  through the gateway, forwarding the caller's existing bearer token, 5s
  timeout, no retries, no soft-fail — a lookup miss or timeout is a hard
  400 back to the caller, since allocation creation has real
  consequences (invoice generation) and must not silently proceed with
  wrong/missing data.

This is the first synchronous inter-service HTTP call in the Django
services (previously all cross-service communication was async via the
outbox/inbox pattern in `suerp_common`). It is deliberately narrow:
one small `resolve_by_email(base_path, email, auth_header)` helper
local to hostel-service, not a new shared library, since only
hostel-service needs it today.

Bulk import runs **synchronously within the request** — one HTTP call
parses the file, creates each allocation in its own DB transaction, and
returns a summary. No async worker/queue. This matches expected load
(tens to low hundreds of rows per warden upload) and the project's
existing local-CPU-constraint guidance to avoid new infra for
low-volume, per-institution operations.

## Changes by service

### auth-service

- `accounts/views.py`: the three `publish_event("user.registered", ...)`
  call sites (`RegisterView`, `AdminCreateUserView`, `PlatformAdminView`)
  add `"email": user.email` to the event payload.
- `shared/event-schemas/user.registered.json`: add `payload.email`
  (string, required).
- New `GET /accounts/users/by-email/?email=...` (`UserByEmailView`):
  returns `{user_id, email, role}`; restricted to `admin`/`platform_admin`
  roles via existing `role_required` decorator. 404 on no match.

### student-service

- `students/models.py`: add `email = models.EmailField(blank=True,
  default="", db_index=True)` to `StudentProfile`. New migration.
- New inbox consumer (first user of `suerp_common.inbox` in this
  service) handling `user.registered`: when `payload.role == "student"`,
  upsert `StudentProfile.email` for the matching `user_id` (create a
  bare profile row if one doesn't exist yet, matching the current
  reality that profile creation and user registration are already
  independent steps).
- New `GET /students/by-email/?email=...` (`StudentByEmailView`):
  returns `{student_id, email}`; restricted to `warden`/`admin` roles.
  404 on no match.

### hostel-service

- New `hostel/lookups.py`: `resolve_by_email(gateway_path, email,
  auth_header) -> dict`, raising a typed `LookupFailed` exception on
  404/timeout/non-2xx. Used for both student and warden lookups.
- `hostel/serializers.py`: `AllocateRequestSerializer.student_id` (UUID)
  → `student_email` (EmailField).
- `hostel/views.py`:
  - Extract the existing create-allocation body (lock room, check
    availability, create `Allocation`, increment `occupied_count`,
    publish `hostel.allocation.requested`, all in
    `transaction.atomic()`) out of `AllocateView.post` into a shared
    `create_allocation(room_id, student_id, tenant) -> Allocation`
    function, reused by both single and bulk create.
  - `AllocateView.post`: resolve `student_email` → `student_id` via
    `resolve_by_email`, then call `create_allocation`. A resolution
    failure returns 400 with the specific reason (not found vs.
    timeout).
  - New `AllocateBulkView` (`POST /hostel/allocate/bulk`,
    `warden`/`admin` only, `MultiPartParser`): accepts one file field.
    Sniffs `.csv`/`.xlsx` by extension (415 on anything else). Parses
    rows expecting `room_id,student_email` columns (stdlib `csv` for
    CSV; `openpyxl` — new dependency — for XLSX). For each row: resolve
    email (memoized per-request dict, since a warden may allocate the
    same student only once in practice but duplicate emails should
    still be handled cheaply), call `create_allocation` in its own
    try/except so one bad row doesn't abort the batch. Writes one
    `AllocationImportBatch` and one `AllocationImportRow` per input row.
    Returns `{batch_id, total_rows, success_count, fail_count}`.
  - New `AllocationImportLogListView` (`GET
    /hostel/allocations/import-logs`) and
    `AllocationImportLogDetailView` (`GET
    /hostel/allocations/import-logs/<id>`), `warden`/`admin` only.
  - New `BlockCreateView` (`POST /hostel/blocks`, admin only): body
    `{name, gender_type, warden_email}`, resolves warden email via
    `resolve_by_email` against auth-service, creates `Block`.
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
- `requirements.txt`: add `openpyxl` (XLSX parsing) and `requests`
  (sync HTTP lookups).

### frontend (`frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx`)

- `CreateAllocation`: room `Input` → `Select` populated from `GET
  /hostel/rooms/available`, labeled `Block / RoomNo (occupied/capacity)`,
  value is the real `room_id`. `studentId` `Input` → `studentEmail`
  `Input` (`type="email"`). POST body: `{room_id, student_email}`.
- New `BulkAllocationImport` component: static "Download sample CSV"
  link (`public/sample-allocation-import.csv`, header
  `room_id,student_email` plus one example row) — no XLSX sample is
  needed since the CSV opens fine in Excel and can be re-saved as
  `.xlsx` if desired; file input accepting `.csv,.xlsx`; upload posts
  multipart to `/api/v1/hostel/allocate/bulk`; renders the returned
  summary inline with a link into the Import Logs tab for the new batch.
- New "Import Logs" tab/panel using the existing `DataPanel` + `Table`
  pattern: batch list (filename, uploaded_at, success/fail counts) from
  `GET /hostel/allocations/import-logs`; selecting a batch shows its
  row-level detail (room_id, email, status, error) from
  `GET /hostel/allocations/import-logs/<id>`.

### frontend (`frontend/su-erp-web/src/app/(dashboard)/admin/page.tsx`)

- New "Hostel Setup" section:
  - Create Block form: name, gender_type select, warden email → `POST
    /hostel/blocks`; table listing existing blocks (`GET
    /hostel/blocks`).
  - Create Room form: block `Select` (from the blocks list above), room
    number, capacity → `POST /hostel/rooms`; table listing existing
    rooms (`GET /hostel/rooms`).

## Error handling

- Email lookup miss (student or warden): 400/404 surfaced verbatim to
  the caller — "No student found with email X" / "No warden found with
  email X" — both for single-create and per-row in bulk (where it
  becomes that row's `error_message`, not a batch-aborting error).
- Lookup timeout/gateway failure: 502 for single-create; for bulk, that
  row is marked failed with a generic "lookup service unavailable"
  message and processing continues to the next row.
- Room unavailable (`is_available == False`): existing behavior
  preserved (400 for single-create, per-row failure in bulk).
- Malformed file (wrong extension, missing columns, unreadable content):
  415/400 before any row processing begins, no batch is created.
- Partial batch failure is expected and not an error state — the
  response and log always report a mix of `success_count`/`fail_count`;
  there's no overall failure unless the file itself couldn't be parsed.

## Testing

- auth-service: event payload includes email (existing outbox test
  pattern); new by-email endpoint permission + 404 cases.
- student-service: new inbox consumer test (event → profile email
  upsert, including the create-if-missing case); new by-email endpoint
  tests (found/not-found/permission).
- hostel-service: `create_allocation` extraction covered by existing
  `test_allocate.py` (should require no behavior change); new tests for
  `AllocateView` with email resolution (success, email-not-found,
  lookup-timeout); `AllocateBulkView` tests covering all-success,
  mixed success/fail, malformed file, wrong extension; import-log list
  and detail view tests; block/room create + list view tests including
  role restrictions.
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
