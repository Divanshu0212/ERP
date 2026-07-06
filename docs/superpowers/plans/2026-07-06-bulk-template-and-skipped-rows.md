# Room-Aware Bulk Template + Skipped-Row Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Warden downloads a CSV of currently-available rooms (with room_id and a
human-readable room_name already filled in) to use as the bulk-allocation upload
template, and rows left with a blank student_email are logged as "skipped" instead of
counted as a failure.

**Architecture:** One new read-only hostel-service endpoint
(`GET /api/v1/hostel/rooms/available-template`) streams a `text/csv` response built
from the same `Room` queryset `AvailableRoomsView` already filters
(`occupied_count__lt=F("capacity")`), ordered by block name then room number. The
existing `AllocateBulkView`/`_parse_rows` bulk-import path gets a new
`AllocationImportRow.Status.SKIPPED` value and a `skipped_count` field on
`AllocationImportBatch`, both denormalized the same way `success_count`/`fail_count`
already are. Frontend swaps the static anchor-tag CSV link for an authenticated
fetch-blob-download (the new endpoint sits behind the same JWT auth as every other
hostel-service route, so a plain `<a href>` can't carry the bearer token).

**Tech Stack:** Django 5 + DRF (hostel-service), Python `csv` module (stdlib, already
used in `_parse_rows`), Next.js/TypeScript frontend, `fetch` + `Blob` +
`URL.createObjectURL` for the authenticated download.

## Global Constraints

- Every hostel-service model is a `suerp_common.tenancy.TenantModel` subclass;
  queries in views must go through the tenant-scoped `objects` manager (not
  `all_objects`), matching every other view in `hostel/views.py`.
- Response envelope for JSON endpoints is `{ success, data, message, errors }` — but
  a CSV-download endpoint returns a raw `HttpResponse` with `Content-Type: text/csv`,
  not the JSON envelope (it's a file download, not a data API call).
- All routes live under `/api/v1/hostel/...` (existing gateway routing, no nginx
  changes needed).
- Follow existing test patterns exactly: `_auth_client`/`_make_room`/`_make_block`
  helpers from `hostel/tests/test_allocate.py`, `pytestmark = pytest.mark.django_db`.
- No new dependencies required for this plan (stdlib `csv` only).

---

### Task 1: Backend — `AllocationImportRow.Status.SKIPPED` + `skipped_count`

**Files:**
- Modify: `services/hostel-service/hostel/models.py:174-221`
  (`AllocationImportBatch`, `AllocationImportRow`)
- Create: `services/hostel-service/hostel/migrations/0004_import_skipped_status.py`
- Modify: `services/hostel-service/hostel/views.py:290-347` (`AllocateBulkView.post`)
- Modify: `services/hostel-service/hostel/serializers.py:81-85`
  (`AllocationImportBatchSerializer`)
- Test: `services/hostel-service/hostel/tests/test_allocate_bulk.py`

**Interfaces:**
- Consumes: `AllocationImportBatch`, `AllocationImportRow` (existing models),
  `_parse_rows` (existing, unchanged — still returns `list[tuple[str, str]]` of
  `(room_id_raw, student_email_raw)`).
- Produces: `AllocationImportRow.Status.SKIPPED = "skipped"`,
  `AllocationImportBatch.skipped_count` (int field), both consumed by Task 2's
  serializer field addition and by the frontend in Task 3.

- [ ] **Step 1: Write the failing test for skipped-row behavior**

Add to `services/hostel-service/hostel/tests/test_allocate_bulk.py` (after
`test_mixed_success_and_failure`):

```python
@patch("hostel.views.resolve_user_by_email")
def test_blank_email_row_is_skipped_not_failed(mock_resolve):
    tenant_id = uuid.uuid4()
    room = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    mock_resolve.return_value = {
        "id": str(uuid.uuid4()),
        "email": "a@example.com",
        "role": "student",
    }
    client = _auth_client(tenant_id, role="warden")

    buf, name = _csv_file([(str(room.id), "")])
    response = _upload(client, buf, name)

    assert response.status_code == 201, response.content
    body = response.json()["data"]
    assert body["total_rows"] == 1
    assert body["success_count"] == 0
    assert body["fail_count"] == 0
    assert body["skipped_count"] == 1

    batch = AllocationImportBatch.all_objects.get(id=body["batch_id"])
    row = batch.rows.get(row_number=1)
    assert row.status == "skipped"
    assert "no email" in row.error_message.lower()
```

Note `_csv_file` (already in the test file) writes `f"{r},{e}"` per row, so
`(str(room.id), "")` produces a trailing-comma CSV row with an empty
`student_email` field — exactly the blank-email case.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/hostel-service && python -m pytest hostel/tests/test_allocate_bulk.py::test_blank_email_row_is_skipped_not_failed -v`
Expected: FAIL — `KeyError: 'skipped_count'` (key not yet in response body).

- [ ] **Step 3: Add `SKIPPED` status and `skipped_count` field to models**

In `services/hostel-service/hostel/models.py`, modify the `AllocationImportBatch`
class (around line 174-196) to add the field:

```python
class AllocationImportBatch(TenantModel):
    """One warden-initiated bulk-allocation upload (CSV or XLSX).

    ``success_count``/``fail_count``/``skipped_count`` are denormalized onto the
    batch (rather than always aggregating ``rows``) so the Import Logs list view
    can show them without an extra query per batch.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uploaded_by = models.UUIDField()
    filename = models.CharField(max_length=255)
    total_rows = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    fail_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"ImportBatch {self.id} ({self.filename})"
```

And modify `AllocationImportRow.Status` (around line 202-204):

```python
    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"
```

- [ ] **Step 4: Generate and apply the migration**

Run: `cd services/hostel-service && python manage.py makemigrations hostel`
Expected: creates `hostel/migrations/0004_import_skipped_status.py` (or similar
auto-generated name — rename the file to
`0004_import_skipped_status.py` if Django picks a different name, for clarity)
adding `skipped_count` to `AllocationImportBatch` and altering the `status` choices
on `AllocationImportRow`.

Run: `python manage.py migrate hostel`
Expected: migration applies cleanly against the test/dev database.

- [ ] **Step 5: Update `AllocateBulkView.post` to skip blank-email rows**

In `services/hostel-service/hostel/views.py`, modify the loop body inside
`AllocateBulkView.post` (currently lines 290-332):

```python
        email_cache: dict[str, dict] = {}
        success_count = 0
        fail_count = 0
        skipped_count = 0

        for row_number, (room_id_raw, student_email_raw) in enumerate(rows, start=1):
            error_message = ""
            allocation = None
            row_status = AllocationImportRow.Status.FAILED

            if not room_id_raw or not student_email_raw:
                error_message = "Row skipped: no email provided."
                row_status = AllocationImportRow.Status.SKIPPED
                skipped_count += 1
            else:
                try:
                    if student_email_raw not in email_cache:
                        email_cache[student_email_raw] = resolve_user_by_email(
                            student_email_raw, auth_header
                        )
                    student = email_cache[student_email_raw]

                    room_uuid = uuid_lib.UUID(room_id_raw)
                    allocation = create_allocation(room_uuid, student["id"], tenant_id)
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
                except ValueError as exc:
                    error_message = str(exc)
                    fail_count += 1

            AllocationImportRow.objects.create(
                tenant_id=tenant_id,
                batch=batch,
                row_number=row_number,
                room_id_raw=room_id_raw,
                student_email_raw=student_email_raw,
                status=row_status,
                error_message=error_message,
                allocation=allocation,
            )

        batch.success_count = success_count
        batch.fail_count = fail_count
        batch.skipped_count = skipped_count
        batch.save(update_fields=["success_count", "fail_count", "skipped_count"])

        return ok(
            {
                "batch_id": str(batch.id),
                "total_rows": len(rows),
                "success_count": success_count,
                "fail_count": fail_count,
                "skipped_count": skipped_count,
            },
            message="Bulk import processed.",
            status=201,
        )
```

This replaces the old `if not room_id_raw or not student_email_raw: raise
ValueError(...)` branch (previously inside the try block, counted as a failure) with
a skip path that never calls `create_allocation` and never touches `fail_count`.

Note the row-number-1-not-0-both-blank edge case is unaffected: if BOTH `room_id_raw`
and `student_email_raw` are blank (a fully empty CSV row), it's still logged as
`SKIPPED`, same as before this only affected email-blank rows in the ticket — but
per the task ("if student email is not written, allocation shouldn't start"), any
missing email skips regardless of whether room_id is present too, which this
condition already covers.

- [ ] **Step 6: Run test to verify it passes**

Run: `cd services/hostel-service && python -m pytest hostel/tests/test_allocate_bulk.py -v`
Expected: all tests PASS, including the new
`test_blank_email_row_is_skipped_not_failed`. Re-check
`test_mixed_success_and_failure` still passes unchanged (it has no blank-email rows,
so behavior there is untouched).

- [ ] **Step 7: Update `AllocationImportBatchSerializer` to expose `skipped_count`**

In `services/hostel-service/hostel/serializers.py`, modify (currently lines 81-85):

```python
class AllocationImportBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = AllocationImportBatch
        fields = [
            "id",
            "filename",
            "total_rows",
            "success_count",
            "fail_count",
            "skipped_count",
            "created_at",
        ]
        read_only_fields = fields
```

(`AllocationImportBatchDetailSerializer` inherits `Meta.fields` by concatenation, so
no separate change needed there — it will automatically include `skipped_count`.)

- [ ] **Step 8: Run the full hostel-service test suite**

Run: `cd services/hostel-service && python -m pytest hostel/ -v`
Expected: all tests PASS (this confirms nothing else — e.g. `test_import_logs.py` —
broke from the new field).

- [ ] **Step 9: Commit**

```bash
git add services/hostel-service/hostel/models.py \
        services/hostel-service/hostel/migrations/ \
        services/hostel-service/hostel/views.py \
        services/hostel-service/hostel/serializers.py \
        services/hostel-service/hostel/tests/test_allocate_bulk.py
git commit -m "feat(hostel): log blank-email bulk-import rows as skipped, not failed"
```

---

### Task 2: Backend — room-aware CSV template endpoint

**Files:**
- Modify: `services/hostel-service/hostel/views.py` (add new view near
  `AvailableRoomsView`, line 48-58)
- Modify: `services/hostel-service/hostel/urls.py:1-34`
- Test: Create `services/hostel-service/hostel/tests/test_available_template.py`

**Interfaces:**
- Consumes: `Room` model (`services/hostel-service/hostel/models.py:41-61`,
  `block.name`, `room_no`, `is_available` via `occupied_count__lt=F("capacity")`
  filter — same condition `AvailableRoomsView` uses at `views.py:58`).
- Produces: `GET /api/v1/hostel/rooms/available-template` — a `text/csv` HTTP
  response, `Content-Disposition: attachment; filename="allocation-template.csv"`,
  body header row `room_id,room_name,student_email` followed by one row per
  available room: `<room.id>,<block.name> - <room.room_no>,` (email column always
  blank). Consumed by Task 3's frontend download button.

- [ ] **Step 1: Write the failing test**

Create `services/hostel-service/hostel/tests/test_available_template.py`:

```python
"""GET /api/v1/hostel/rooms/available-template — CSV download of available rooms,
pre-filled with room_id and room_name so a warden can fill in student_email and
re-upload it directly to /api/v1/hostel/allocate/bulk.
"""

import csv
import io
import uuid

import pytest

pytestmark = pytest.mark.django_db

from hostel.tests.test_allocate import _auth_client, _make_block, _make_room  # noqa: E402
from hostel.models import Room


def test_returns_only_available_rooms_as_csv():
    tenant_id = uuid.uuid4()
    available = _make_room(tenant_id, capacity=2, occupied_count=0, room_no="101")
    full = _make_room(tenant_id, capacity=1, occupied_count=1, room_no="102")
    client = _auth_client(tenant_id, role="warden")

    response = client.get("/api/v1/hostel/rooms/available-template")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]

    content = response.content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    assert reader.fieldnames == ["room_id", "room_name", "student_email"]
    rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["room_id"] == str(available.id)
    assert rows[0]["room_name"] == f"{available.block.name} - {available.room_no}"
    assert rows[0]["student_email"] == ""
    assert str(full.id) not in content


def test_ordered_by_block_then_room_no():
    tenant_id = uuid.uuid4()
    block_a = _make_block(tenant_id)
    block_a.name = "Block A"
    block_a.save(update_fields=["name"])
    room_b2 = Room.all_objects.create(
        tenant_id=tenant_id, block=block_a, room_no="B2", capacity=2, occupied_count=0
    )
    room_a1 = Room.all_objects.create(
        tenant_id=tenant_id, block=block_a, room_no="A1", capacity=2, occupied_count=0
    )
    client = _auth_client(tenant_id, role="warden")

    response = client.get("/api/v1/hostel/rooms/available-template")
    content = response.content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    room_ids_in_order = [row["room_id"] for row in reader]

    assert room_ids_in_order == [str(room_a1.id), str(room_b2.id)]


def test_student_role_forbidden():
    tenant_id = uuid.uuid4()
    client = _auth_client(tenant_id, role="student")

    response = client.get("/api/v1/hostel/rooms/available-template")

    assert response.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/hostel-service && python -m pytest hostel/tests/test_available_template.py -v`
Expected: FAIL with 404 (URL doesn't exist yet).

- [ ] **Step 3: Add the view**

In `services/hostel-service/hostel/views.py`, add a new import at the top (extend
the existing `import csv` and `import io` lines already present at lines 18-19 — no
new import needed there) and add this class directly after `AvailableRoomsView`
(after line 58, before `class BlockListCreateView`):

```python
class AvailableRoomsTemplateView(APIView):
    """GET /api/v1/hostel/rooms/available-template — CSV download of available
    rooms, pre-filled with room_id/room_name so a warden only has to type in
    student_email before re-uploading to /api/v1/hostel/allocate/bulk.

    Returns a raw text/csv HttpResponse, not the JSON envelope — this is a file
    download, not a data API call, same as the frontend's earlier static-asset
    link it replaces.
    """

    permission_classes = [role_required("warden", "admin")]

    def get(self, request):
        from django.http import HttpResponse

        rooms = (
            Room.objects.filter(occupied_count__lt=F("capacity"))
            .select_related("block")
            .order_by("block__name", "room_no")
        )

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["room_id", "room_name", "student_email"])
        for room in rooms:
            writer.writerow([str(room.id), f"{room.block.name} - {room.room_no}", ""])

        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="allocation-template.csv"'
        return response
```

(`from django.http import HttpResponse` is scoped to the method rather than added to
the top-level imports, matching this being the only view in the file that returns a
non-enveloped response — keeps the distinction visually obvious at the call site.)

- [ ] **Step 4: Wire the URL**

In `services/hostel-service/hostel/urls.py`, add the import and route:

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
    RoomListCreateView,
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
]
```

Note: `rooms/available-template` is registered **before** `rooms/available` is
irrelevant here since Django matches full literal path segments, not prefixes, but
the route is placed above it for readability (template-download alongside its
JSON-listing sibling).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/hostel-service && python -m pytest hostel/tests/test_available_template.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 6: Run the full hostel-service test suite**

Run: `cd services/hostel-service && python -m pytest hostel/ -v`
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add services/hostel-service/hostel/views.py \
        services/hostel-service/hostel/urls.py \
        services/hostel-service/hostel/tests/test_available_template.py
git commit -m "feat(hostel): add CSV template endpoint listing available rooms"
```

---

### Task 3: Frontend — authenticated CSV download + skipped-row display

**Files:**
- Modify: `frontend/su-erp-web/src/lib/api.ts:104-121` (add a new export)
- Modify: `frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx:263-451`
  (`BulkImportSummary` interface, `BulkAllocationImport`, `ImportBatch`,
  `ImportRow`, `ImportLogs`)

**Interfaces:**
- Consumes: `GET /api/v1/hostel/rooms/available-template` (Task 2),
  `authHeaders()` (existing, `api.ts:42-47`, unexported — the new function lives in
  the same file so it can call it directly).
- Produces: `downloadFile(path: string, filename: string): Promise<void>` exported
  from `src/lib/api.ts`, used by `BulkAllocationImport`.

- [ ] **Step 1: Add an authenticated blob-download helper to `api.ts`**

In `frontend/su-erp-web/src/lib/api.ts`, add after `apiUpload` (after line 121,
before the `export const api = {` block):

```ts
/**
 * Download a file from an authenticated endpoint and trigger a browser save.
 * Distinct from apiCall/apiUpload: the response is a raw file (not the JSON
 * envelope), so this fetches, reads a Blob, and drives an anchor-click download
 * instead of calling `unwrap`.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
  const url = buildUrl(path);
  const headers = authHeaders();

  let response: Response;
  try {
    response = await fetch(url, { method: "GET", headers });
  } catch (cause) {
    const detail = cause instanceof Error ? cause.message : String(cause);
    throw new ApiError(`Network error calling GET ${path}: ${detail}`);
  }

  if (!response.ok) {
    throw new ApiError(`Download failed for ${path} (status ${response.status})`, response.status);
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(objectUrl);
}
```

Then add it to the `api` convenience object (modify the existing block at the end
of the file):

```ts
export const api = {
  get: <T = unknown>(path: string) => apiCall<T>("GET", path),
  post: <T = unknown>(path: string, body?: unknown) => apiCall<T>("POST", path, body),
  put: <T = unknown>(path: string, body?: unknown) => apiCall<T>("PUT", path, body),
  patch: <T = unknown>(path: string, body?: unknown) => apiCall<T>("PATCH", path, body),
  delete: <T = unknown>(path: string) => apiCall<T>("DELETE", path),
  upload: <T = unknown>(path: string, file: File, fieldName?: string) =>
    apiUpload<T>(path, file, fieldName),
  download: (path: string, filename: string) => downloadFile(path, filename),
};
```

- [ ] **Step 2: Replace the static anchor with a download button in `BulkAllocationImport`**

In `frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx`, modify the
`BulkImportSummary` interface (currently lines 263-268):

```tsx
interface BulkImportSummary {
  batch_id: string;
  total_rows: number;
  success_count: number;
  fail_count: number;
  skipped_count: number;
}
```

Modify `BulkAllocationImport` (currently lines 270-329) — replace the static anchor
(lines 299-305) with a button, and add a `templateError` state:

```tsx
function BulkAllocationImport({ onImported }: { onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<BulkImportSummary | null>(null);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [templatePending, setTemplatePending] = useState(false);

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

  async function downloadTemplate() {
    setTemplatePending(true);
    setTemplateError(null);
    try {
      await api.download("/api/v1/hostel/rooms/available-template", "allocation-template.csv");
    } catch (err) {
      setTemplateError(errMsg(err));
    } finally {
      setTemplatePending(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Bulk allocate from CSV/XLSX" />
      <CardBody>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <Button type="button" variant="ghost" size="sm" loading={templatePending} onClick={downloadTemplate}>
              Download available-rooms template
            </Button>
            {templateError && <Alert tone="error">{templateError}</Alert>}
          </div>
          <Field label="File" htmlFor="bulk-file">
            <input
              id="bulk-file"
              type="file"
              accept=".csv,.xlsx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm text-ink"
            />
          </Field>
          {error && <Alert tone="error">{error}</Alert>}
          {summary && (
            <Alert tone={summary.fail_count > 0 ? "info" : "success"}>
              {summary.success_count} succeeded, {summary.fail_count} failed,{" "}
              {summary.skipped_count} skipped out of {summary.total_rows}. See Import
              Logs below for details.
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

- [ ] **Step 3: Add `skipped_count` to `ImportBatch` and the batches table**

Modify the `ImportBatch` interface (currently lines 331-338):

```tsx
interface ImportBatch {
  id: string;
  filename: string;
  total_rows: number;
  success_count: number;
  fail_count: number;
  skipped_count: number;
  created_at: string;
}
```

Modify the batches `<Table>` inside `ImportLogs` (currently lines 393-418) to add a
"Skipped" column:

```tsx
      <Table>
        <THead>
          <HeaderRow>
            <TH>File</TH>
            <TH>Uploaded</TH>
            <TH>Success</TH>
            <TH>Failed</TH>
            <TH>Skipped</TH>
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
              <TD>{b.skipped_count}</TD>
              <TD>
                <Button variant="ghost" size="sm" onClick={() => viewBatch(b.id)}>
                  View
                </Button>
              </TD>
            </Row>
          ))}
        </TBody>
      </Table>
```

The per-row detail table (lines 424-448, `ImportRow`/`StatusPill`) needs no change —
`StatusPill` already falls back to a neutral tone for any status string it doesn't
recognize (`src/components/ui/StatusPill.tsx`), so `"skipped"` renders correctly
without a code change there.

- [ ] **Step 4: Remove the now-unused static sample CSV asset**

The static file is no longer linked from anywhere in the app after Step 2 replaced
its anchor tag.

Run: `git rm frontend/su-erp-web/public/sample-allocation-import.csv`

- [ ] **Step 5: Manually verify in the browser**

Run: `cd frontend/su-erp-web && npm run dev` (ensure the backend stack from
`infra/docker-compose.yml` is up per `docs/RUNBOOK.md` so the warden page has data
to hit).

Log in as a warden, open the warden dashboard, click "Download available-rooms
template" — confirm a `allocation-template.csv` downloads with header
`room_id,room_name,student_email` and one row per available room. Confirm a login as
a student role gets a 403 if hitting the endpoint directly (expected, not exposed in
the student UI at all).

Upload a CSV with one row that has a room_id but blank student_email — confirm the
summary alert shows "... 1 skipped out of 1" and the Import Logs detail table shows
that row with a neutral "skipped" pill instead of a red "failed" one.

- [ ] **Step 6: Run frontend lint/build to catch type errors**

Run: `cd frontend/su-erp-web && npm run lint && npm run build`
Expected: no errors (confirms the new `ImportBatch`/`BulkImportSummary` fields and
`api.download` are type-correct throughout).

- [ ] **Step 7: Commit**

```bash
git add frontend/su-erp-web/src/lib/api.ts \
        "frontend/su-erp-web/src/app/(dashboard)/warden/page.tsx" \
        frontend/su-erp-web/public/sample-allocation-import.csv
git commit -m "feat(warden-ui): download room-filled CSV template, show skipped-row counts"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 covers "blank email rows shouldn't start allocation" +
  skipped-status logging (per the approved design). Task 2 covers "download CSV with
  room ids and room names already in it." Task 3 covers the frontend wiring for
  both, plus removing the now-dead static sample file. All three README design-doc
  bullets under "1. Room-aware bulk allocation template" are implemented.
- **Type consistency checked:** `AllocationImportRow.Status.SKIPPED = "skipped"`
  (Task 1) matches the `"skipped"` string checked in Task 3's `StatusPill` fallback
  note and the `row.status == "skipped"` assertion in Task 1's test. `skipped_count`
  field name is identical across the model (Task 1), serializer (Task 1),
  view response body (Task 1), and the `BulkImportSummary`/`ImportBatch` TS
  interfaces (Task 3). `AvailableRoomsTemplateView` (Task 2) is the exact class name
  imported in `urls.py` and referenced nowhere else.
- **No placeholders:** every step has complete code, not descriptions of code.
