# Bulk student upload + dedicated admin "Add Students" page

Date: 2026-07-13
Status: Approved, ready for planning

## Problem

The admin dashboard's "Add user" form creates one `User` at a time and has
no student-profile fields (department/batch/semester). There is no way to
onboard a class roster in bulk, and no dedicated page for student
provisioning — it's mixed in with invoices, fee structures, and hostel
setup on the single `/admin` page.

## Architecture

Two services own two different tables for a student: auth-service's `User`
(identity/login) and student-service's `StudentProfile` (department/batch/
semester/cgpa). Per [[su-erp-stack-decisions]] and the existing
`hostel-service/consumers.py` saga pattern, services never call each other
synchronously for state changes — they communicate async via the
transactional outbox (`publish_event` + a per-service consumer). The
2026-07-04 bulk-allocation-import spec establishes the one deliberate
exception to that (a synchronous *read-only lookup* through the gateway),
which doesn't apply here since nothing needs to resolve an unknown
identifier mid-request — the admin's own tenant is already known from the
JWT.

So bulk student creation splits across the existing boundary:

- **auth-service**, synchronous, in-request: a new bulk endpoint creates
  all `User` rows (role=student) directly, one DB transaction per row, and
  publishes one `user.registered` event per success — same event type
  RegisterView/UserAdminView already emit, just with three extra payload
  fields (`department`, `batch`, `semester`) that only matter to
  student-service. Runs fully in-request, no queue, matching the local-CPU
  guidance ([[su-erp-local-cpu-constraint]]) and the precedent set by the
  2026-07-04 bulk-allocation import (in-request CSV processing, no async
  worker).
- **student-service**, async, via a new consumer: reacts to
  `user.registered` and creates the matching `StudentProfile` when
  `payload["role"] == "student"`. This is a genuinely new capability for
  student-service (it currently has zero consumers) but requires no new
  library — `suerp_common.inbox.idempotent` and the outbox already exist
  and are used by every other service's consumers.

This means the frontend gets full per-row success/fail feedback for the
`User` half synchronously (email/user_code conflicts, bad rows) — the part
that can actually fail in a way the admin needs to fix. The `StudentProfile`
half has no meaningful failure mode (department/batch/semester are free-text
with no uniqueness constraint) so async-and-silent is an acceptable
trade-off, not a gap: the UI states created students' profiles sync in
the background rather than claiming synchronous confirmation it can't give.

Single-student creation on the new page reuses the same bulk endpoint with
a one-row payload — no separate single-create endpoint, so there's exactly
one code path to test and keep consistent between "add one student" and
"add many."

## Changes by service

### auth-service

- New `POST /api/v1/auth/users/bulk/` (`UserBulkCreateView`, admin-only via
  existing `role_required("admin")`). Body: `{"rows": [{"email", "user_code",
  "password", "department", "batch", "semester"}, ...]}`. `role` is not
  accepted per-row — every row is created as `role="student"` (this
  endpoint is student-only, matching the page name and the ask).
  - For each row, in its own `transaction.atomic()`: validate via
    `AdminCreateUserSerializer`-equivalent rules (reuses the existing
    `AdminCreateUserSerializer` for the User fields, extended with
    `department: CharField`, `batch: CharField`,
    `semester: IntegerField(default=1)`), create the `User`, publish
    `user.registered` with payload `{"user_code", "role": "student",
    "department", "batch", "semester"}`. A failure in one row (duplicate
    email/user_code within the tenant, or within the same upload batch;
    bad email format; short password) is caught, recorded, and does NOT
    abort the remaining rows — matches the 2026-07-04 spec's partial-
    failure precedent.
  - Response: `{"created": [{"row", "email", "user_code"}, ...], "failed":
    [{"row", "email", "error"}, ...]}`.
  - Malformed request (not a list, empty list, missing required top-level
    key) is rejected 400 before any row processing.

### student-service

- New `students/consumers.py`: `handle_user_registered(event)`, decorated
  `@idempotent`. Reads `event["payload"]`; if `payload.get("role") !=
  "student"`, return (no-op — every role's registration flows through the
  same `user.registered` type, e.g. wardens/faculty, which student-service
  must ignore). Otherwise creates `StudentProfile(tenant_id=event
  ["tenant_id"], user_code=payload["user_code"], department=payload.get
  ("department", ""), batch=payload.get("batch", ""), semester=payload.get
  ("semester", 1))` inside `transaction.atomic()`. Uses `StudentProfile
  .all_objects.get_or_create(...)` keyed on `(tenant_id, user_code)` so a
  replayed event is a no-op even beyond the `@idempotent` guard, consistent
  with the `get_or_create`-for-belt-and-suspenders pattern already used in
  `hostel/consumers.py`.
- `students/models.py`: add `unique_together = [("tenant_id", "user_code")]`
  (or equivalent) to `StudentProfile.Meta` — currently absent; needed for
  `get_or_create` to be meaningfully idempotent and because two profiles
  for one user_code would be a data bug regardless of this feature.
- New consumer process wiring (`manage.py consume_events` entrypoint / the
  per-service `dispatch()` function) following the exact shape of
  `hostel/consumers.py`'s `dispatch()` — binds to `user.registered` in this
  service's queue.
- `docker-compose.yml`: student-service needs its own consumer worker
  entry (mirroring the existing pattern per [[su-erp-local-cpu-constraint]]
  — each service gets its own Celery/consumer queue, opt-in via compose
  profiles consistent with how other services are wired).

### frontend

- New page `frontend/su-erp-web/src/app/(dashboard)/admin/students/new/page.tsx`:
  - `AddStudentForm`: single-student form — email, user_code, password,
    department, batch, semester — posts `{"rows": [{...one row}]}` to
    `/api/v1/auth/users/bulk/`, reusing the same endpoint as bulk (see
    Architecture). Success/error rendered the same way as the existing
    admin "Add user" form (`Alert` tone success/error).
  - `BulkStudentUpload`: file input accepting `.csv`; parses client-side
    (small dependency-free CSV parser — the file is expected to be
    small/simple, comma-separated, quoted-field support not required given
    the fixed known-safe column set); expects header row exactly
    `email,user_code,password,department,batch,semester`; builds the
    `rows` array and POSTs to the same bulk endpoint. Renders a results
    table: one row per submitted CSV row, columns Row/Email/Status
    (created in green / failed in red with the `error` message). A static
    "Download sample CSV" link
    (`public/sample-student-upload.csv`, header row + one example line)
    matching the 2026-07-04 spec's convention.
  - Both forms live on one page (per user selection), share nothing beyond
    the page shell — no shared React state, since a bulk upload and a
    one-off add are independent actions an admin might do in either order.
- `frontend/su-erp-web/src/components/DashboardShell.tsx`: add one entry to
  the `admin` array in `NAV` — `{ label: "Add Students", href:
  "/admin/students/new", icon: GraduationCap }` (icon already imported and
  used by the `faculty` nav entry; reused here rather than importing a new
  icon for the same concept).

## Error handling

- Row-level validation/duplicate errors (email/user_code already used, in
  DB or earlier in the same file) never abort the batch — same
  partial-failure contract as `AllocateBulkView`.
- Malformed CSV (wrong header, unreadable file, zero data rows): rejected
  client-side before any request is sent, with an inline error — no
  network round-trip for a file that can't possibly parse.
- The 400 for a structurally invalid *request body* (not a CSV problem —
  e.g. someone hitting the API directly with garbage) is a whole-request
  400 with no partial processing, since there's nothing row-shaped to
  process yet.
- `StudentProfile` creation failures (should not occur under normal
  operation — no uniqueness collision is user-triggerable at that layer
  since `user_code` uniqueness is already enforced at the `User` layer
  synchronously) are logged server-side only; the UI's "created" state
  reflects the `User` row and states profile sync is in progress, not
  guaranteed-complete.

## Testing

- auth-service: `UserBulkCreateView` tests — all-success, mixed
  success/fail (duplicate email mid-batch, duplicate user_code mid-batch,
  invalid email format), empty rows list (400), non-admin role rejected,
  cross-tenant isolation (row targets don't leak), event payload shape
  assertion (department/batch/semester present).
- student-service: new `handle_user_registered` consumer tests — creates
  StudentProfile for role=student, no-ops for role=warden/faculty/etc,
  idempotent replay (same event_id twice = one row), `get_or_create`
  collision (same user_code twice = one row, no crash).
- frontend: new `students/new` page test — single-form submit success/
  error, CSV upload parse + submit + results table render (mock a mixed
  success/fail API response), malformed CSV client-side rejection; extend
  `DashboardShell` nav test if one exists, else cover via the new page's
  render including the sidebar.

## Out of scope

- Editing or deleting bulk-uploaded students (create-only, matching the
  existing single "Add user" form's scope).
- XLSX support (CSV only — the 2026-07-04 spec added XLSX because wardens
  already worked with spreadsheets exported from elsewhere; no such
  constraint stated here, and CSV keeps the client-side parser trivial).
- Attendance/academic "logs" of any kind attached to the upload (explicitly
  descoped in brainstorming — "logs" here means the upload's own
  success/fail activity log, not student attendance history).
- A persisted, queryable upload-batch history (unlike the 2026-07-04
  hostel import, which added `AllocationImportBatch`/`Row` models + a log
  viewer tab). The bulk response is shown once, inline, on submit; nothing
  is stored for later review. Add if a real need for historical audit
  shows up.
- Bulk creation of non-student roles (faculty/warden/etc.) — this page and
  endpoint are student-only by design.
