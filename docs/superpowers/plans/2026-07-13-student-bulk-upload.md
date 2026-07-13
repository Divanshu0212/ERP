# Bulk Student Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin bulk-create students (User + StudentProfile) via CSV upload or a single-student form, on a new dedicated `/admin/students/new` page reachable from the admin sidebar.

**Architecture:** A new synchronous, admin-only `POST /api/v1/auth/users/bulk/` in auth-service creates `User` rows (role=student) one DB transaction per row, best-effort (bad rows don't abort the batch), and publishes one `user.registered` event per success carrying `department`/`batch`/`semester`. A new consumer in student-service (`students/consumers.py`, wired via a new `manage.py consume_events`) reacts to that event asynchronously and creates the matching `StudentProfile`, no-op for non-student roles, idempotent via `@idempotent` + `get_or_create`. The frontend gets one new page with a single-student form and a CSV-upload widget, both posting to the same bulk endpoint (a one-row array in the single-add case), plus one new sidebar entry.

**Tech Stack:** Django REST Framework (auth-service, student-service), suerp_common (outbox/inbox), RabbitMQ topic exchange, Next.js/React/TypeScript (frontend), pytest + APIClient (backend tests), existing Jest/RTL setup (frontend tests, matching `*.test.tsx` siblings already in the repo).

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-07-13-student-bulk-upload-design.md` — every task below implements a section of it; deviate only if this plan's investigation found the spec wrong, and note why.
- No new cross-service synchronous calls — StudentProfile creation MUST stay async via the outbox/consumer pattern (spec Architecture section).
- Endpoint is student-only: bulk-created rows are always `role="student"`, no per-row role field.
- Partial-failure semantics: one bad row never aborts the batch (spec's "Create all valid rows, report failures per-row" decision).
- CSV column order/header, exact: `email,user_code,password,department,batch,semester`.
- Response shape from `POST /api/v1/auth/users/bulk/`: `{"created": [{"row", "email", "user_code"}, ...], "failed": [{"row", "email", "error"}, ...]}`.
- Commit after each task (per user's cadence preference) — every task ends with its own commit on `feature/student-bulk-upload`.
- Follow this repo's existing patterns exactly where one exists (outbox publish shape, `role_required`, `TenantModel`, `@idempotent`, `make_consumer`/`dispatch`, envelope `ok`/`fail`, existing frontend `api.post`/`Card`/`Field`/`Alert`/`Table` components) — do not invent new abstractions.

---

## File Structure

**auth-service:**
- Modify `services/auth-service/accounts/serializers.py` — add `BulkCreateStudentRowSerializer` (extends the existing field set from `AdminCreateUserSerializer` with `department`, `batch`, `semester`; role is NOT a field, it's hardcoded).
- Modify `services/auth-service/accounts/views.py` — add `UserBulkCreateView`.
- Modify `services/auth-service/accounts/urls.py` — wire `users/bulk/`.
- Create `services/auth-service/accounts/tests/test_bulk_create.py`.

**student-service:**
- Modify `services/student-service/students/models.py` — add `unique_together` to `StudentProfile.Meta`.
- Create `services/student-service/students/migrations/0002_studentprofile_unique_tenant_user_code.py` (generated, not hand-written).
- Create `services/student-service/students/consumers.py` — `handle_user_registered` + `dispatch`.
- Create `services/student-service/students/management/__init__.py`, `.../commands/__init__.py`, `.../commands/consume_events.py` (mirrors `hostel-service`'s structure exactly).
- Create `services/student-service/students/tests/test_consumers.py`.
- Modify `infra/docker-compose.yml` — add `&student-build`/`&student-env` anchors to the existing `student-service` block, plus a new `student-consumer` service entry.

**frontend:**
- Create `frontend/su-erp-web/src/app/(dashboard)/admin/students/new/page.tsx` — `AddStudentForm` + `BulkStudentUpload`, both posting to the bulk endpoint.
- Create `frontend/su-erp-web/src/app/(dashboard)/admin/students/new/students-new.test.tsx` (matches this repo's `<route>.test.tsx` co-location convention, e.g. `admin/admin.test.tsx`).
- Modify `frontend/su-erp-web/src/components/DashboardShell.tsx` — add "Add Students" to the `admin` NAV array.
- Create `frontend/su-erp-web/public/sample-student-upload.csv`.

---

## Task 1: auth-service — bulk row serializer

**Files:**
- Modify: `services/auth-service/accounts/serializers.py`
- Test: covered by Task 2's view tests (a bare serializer has no meaningful standalone behavior worth testing before it's wired to a view — this repo's existing serializers are all tested through their views, e.g. `AdminCreateUserSerializer` has no dedicated serializer test file).

**Interfaces:**
- Consumes: `accounts.models.User`, `accounts.models.Institution` (existing).
- Produces: `BulkCreateStudentRowSerializer` — a `serializers.Serializer` subclass with fields `email` (EmailField), `user_code` (RegexField `^[A-Za-z0-9_-]{1,30}$`), `password` (CharField, write_only, min_length=8), `department` (CharField, max_length=100), `batch` (CharField, max_length=20), `semester` (IntegerField, default=1, min_value=1). `.validate(attrs)` takes `self.context["institution"]` and `self.context["seen_user_codes"]`/`self.context["seen_emails"]` (sets passed in by the view, tracking prior rows in the SAME batch — see Task 2) and raises on: email already exists in tenant, user_code already exists in tenant, email already used earlier in this same batch, user_code already used earlier in this same batch. `.create(validated_data)` returns a `User` via `User.objects.create_user(tenant=institution, email=..., password=..., role=User.Role.STUDENT, user_code=...)` — mirrors `AdminCreateUserSerializer.create` exactly, with `role` hardcoded instead of read from `validated_data`.

- [ ] **Step 1: Read the existing `AdminCreateUserSerializer` for the exact pattern to extend**

Already read at `services/auth-service/accounts/serializers.py:80-111` in this session — reuse its `validate`/`create` shape verbatim, adding the three profile fields and the in-batch duplicate checks.

- [ ] **Step 2: Add the new serializer**

Insert immediately after `AdminCreateUserSerializer` (after line 111) in `services/auth-service/accounts/serializers.py`:

```python
class BulkCreateStudentRowSerializer(serializers.Serializer):
    """One row of a bulk student-creation batch. Always creates role=student —
    there is no role field, unlike AdminCreateUserSerializer. Cross-row
    duplicate checks (within the same upload) are enforced via
    context["seen_emails"]/context["seen_user_codes"], mutated by the caller
    (UserBulkCreateView) as each row is accepted, so row 5 catching a
    duplicate of row 2 fails only row 5."""

    email = serializers.EmailField()
    user_code = serializers.RegexField(r"^[A-Za-z0-9_-]{1,30}$")
    password = serializers.CharField(
        write_only=True, min_length=8, style={"input_type": "password"}
    )
    department = serializers.CharField(max_length=100)
    batch = serializers.CharField(max_length=20)
    semester = serializers.IntegerField(default=1, min_value=1)

    def validate(self, attrs):
        institution = self.context["institution"]
        seen_emails = self.context["seen_emails"]
        seen_user_codes = self.context["seen_user_codes"]
        email = User.objects.normalize_email(attrs["email"])
        user_code = attrs["user_code"]

        if email in seen_emails:
            raise serializers.ValidationError({"email": "Duplicate email earlier in this upload."})
        if user_code in seen_user_codes:
            raise serializers.ValidationError(
                {"user_code": "Duplicate user_code earlier in this upload."}
            )
        if User.objects.filter(tenant=institution, email=email).exists():
            raise serializers.ValidationError({"email": "A user with this email already exists."})
        if User.objects.filter(tenant=institution, user_code=user_code).exists():
            raise serializers.ValidationError(
                {"user_code": "A user with this user_code already exists."}
            )
        attrs["email"] = email
        return attrs

    def create(self, validated_data):
        institution = self.context["institution"]
        return User.objects.create_user(
            tenant=institution,
            email=validated_data["email"],
            password=validated_data["password"],
            role=User.Role.STUDENT,
            user_code=validated_data["user_code"],
        )
```

- [ ] **Step 3: Commit**

```bash
git add services/auth-service/accounts/serializers.py
git commit -m "feat(auth-service): add BulkCreateStudentRowSerializer"
```

---

## Task 2: auth-service — bulk create view + URL

**Files:**
- Modify: `services/auth-service/accounts/views.py`
- Modify: `services/auth-service/accounts/urls.py`
- Test: `services/auth-service/accounts/tests/test_bulk_create.py`

**Interfaces:**
- Consumes: `BulkCreateStudentRowSerializer` (Task 1), `accounts.models.Institution`, `suerp_common.envelope.{ok,fail}`, `suerp_common.outbox.publish_event`, `suerp_common.permissions.role_required`.
- Produces: `UserBulkCreateView` at `POST /api/v1/auth/users/bulk/`, response envelope `data = {"created": [{"row": int, "email": str, "user_code": str}], "failed": [{"row": int, "email": str, "error": str}]}`.

- [ ] **Step 1: Write the failing tests**

Create `services/auth-service/accounts/tests/test_bulk_create.py`:

```python
"""POST /api/v1/auth/users/bulk/ — admin bulk student creation.

Covers: all-success, mixed success/fail (dup email/user_code against
existing DB rows AND against earlier rows in the same batch), permission
(admin-only), malformed body, and the user.registered event payload
carrying department/batch/semester for the consumer in student-service.
"""

import pytest
from accounts.models import Institution, User
from rest_framework.test import APIClient
from suerp_common.outbox import OutboxEvent

pytestmark = pytest.mark.django_db


def _make_institution(slug="alpha", name="Alpha University"):
    return Institution.objects.create(slug=slug, name=name, is_active=True)


@pytest.fixture
def client():
    return APIClient()


_user_code_counter = 0


def _next_user_code():
    global _user_code_counter
    _user_code_counter += 1
    return f"USR-{_user_code_counter:04d}"


def _register(client, institution, email, password="s3cur3-passw0rd", role=None, user_code=None):
    payload = {
        "institution_slug": institution.slug,
        "email": email,
        "password": password,
        "user_code": user_code or _next_user_code(),
    }
    if role is not None:
        payload["role"] = role
    return client.post("/api/v1/auth/register", payload, format="json")


def _token(client, institution, email, password="s3cur3-passw0rd"):
    resp = client.post(
        "/api/v1/auth/login",
        {"institution_slug": institution.slug, "email": email, "password": password},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    return resp.json()["data"]["access"]


def _admin_token(client, institution, email="admin@example.com"):
    _register(client, institution, email=email, role=User.Role.ADMIN)
    return _token(client, institution, email)


def _row(email="stu1@example.com", user_code="STU-0001", password="n3w-passw0rd",
         department="CS", batch="2026", semester=1):
    return {
        "email": email,
        "user_code": user_code,
        "password": password,
        "department": department,
        "batch": batch,
        "semester": semester,
    }


def test_bulk_create_all_success(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {"rows": [
            _row(email="a@example.com", user_code="STU-A"),
            _row(email="b@example.com", user_code="STU-B"),
        ]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert len(data["created"]) == 2
    assert data["failed"] == []
    assert {c["email"] for c in data["created"]} == {"a@example.com", "b@example.com"}

    a = User.objects.get(tenant=inst, email="a@example.com")
    assert a.role == User.Role.STUDENT
    assert a.check_password("n3w-passw0rd") is True

    events = OutboxEvent.objects.filter(type="user.registered", payload__user_code="STU-A")
    assert events.count() == 1
    payload = events.first().payload
    assert payload["role"] == User.Role.STUDENT
    assert payload["department"] == "CS"
    assert payload["batch"] == "2026"
    assert payload["semester"] == 1


def test_bulk_create_mixed_success_and_failure_does_not_abort_batch(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)
    _register(client, inst, email="existing@example.com", role=User.Role.STUDENT, user_code="EXIST-1")

    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {"rows": [
            _row(email="good@example.com", user_code="STU-GOOD"),
            _row(email="existing@example.com", user_code="STU-DUPE-EMAIL"),  # dup email vs DB
            _row(email="dupcode@example.com", user_code="EXIST-1"),  # dup user_code vs DB
        ]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert len(data["created"]) == 1
    assert data["created"][0]["email"] == "good@example.com"
    assert len(data["failed"]) == 2
    failed_rows = {f["row"] for f in data["failed"]}
    assert failed_rows == {1, 2}  # 0-indexed: row 0 succeeded
    assert User.objects.filter(tenant=inst, email="good@example.com").exists()
    assert not User.objects.filter(tenant=inst, email="dupcode@example.com").exists()


def test_bulk_create_rejects_duplicate_within_same_batch(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {"rows": [
            _row(email="same@example.com", user_code="STU-SAME-1"),
            _row(email="same@example.com", user_code="STU-SAME-2"),
        ]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 201, resp.content
    data = resp.json()["data"]
    assert len(data["created"]) == 1
    assert len(data["failed"]) == 1
    assert data["failed"][0]["row"] == 1


def test_bulk_create_empty_rows_is_400(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {"rows": []},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 400
    assert resp.json()["success"] is False


def test_bulk_create_missing_rows_key_is_400(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 400


def test_bulk_create_forbidden_for_student(client):
    inst = _make_institution()
    _register(client, inst, email="student@example.com", role=User.Role.STUDENT)
    token = _token(client, inst, "student@example.com")

    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {"rows": [_row()]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 403


def test_bulk_create_requires_authentication(client):
    resp = client.post("/api/v1/auth/users/bulk/", {"rows": [_row()]}, format="json")
    assert resp.status_code == 401


def test_bulk_create_isolated_per_tenant(client):
    inst_a = _make_institution(slug="alpha", name="Alpha University")
    inst_b = _make_institution(slug="beta", name="Beta University")
    admin_token_a = _admin_token(client, inst_a)
    _register(client, inst_b, email="stu@example.com", role=User.Role.STUDENT, user_code="STU-B1")

    # Same email exists in tenant B but not tenant A — must succeed for A.
    resp = client.post(
        "/api/v1/auth/users/bulk/",
        {"rows": [_row(email="stu@example.com", user_code="STU-A1")]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token_a}",
    )

    assert resp.status_code == 201, resp.content
    assert len(resp.json()["data"]["created"]) == 1
    assert User.objects.filter(tenant=inst_a, email="stu@example.com").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/auth-service && python -m pytest accounts/tests/test_bulk_create.py -v`
Expected: FAIL — `404` on the URL (not wired yet) or import error.

- [ ] **Step 3: Add the view**

In `services/auth-service/accounts/views.py`, add `BulkCreateStudentRowSerializer` to the existing import block (line 13-24), and add this class after `UserAdminView` (after line 258):

```python
class UserBulkCreateView(APIView):
    """POST /api/v1/auth/users/bulk/ — admin bulk-creates students.

    Every row becomes role=student (no per-row role field — this endpoint is
    student-only by design). Each row is validated and saved in its OWN
    transaction.atomic(), so one bad row (duplicate email/user_code, either
    against the DB or against an earlier row in this same upload) does not
    abort the rest of the batch — matches the partial-failure contract used
    by hostel-service's bulk allocation import.

    department/batch/semester ride along in the user.registered payload
    purely for student-service's consumer to pick up (see
    students/consumers.py) — auth-service does not otherwise use them.
    """

    permission_classes = [role_required("admin")]

    def post(self, request):
        rows = request.data.get("rows")
        if not isinstance(rows, list) or len(rows) == 0:
            return fail("Request must include a non-empty 'rows' list.", status=400)

        try:
            institution = Institution.objects.get(pk=request.user.tenant_id)
        except Institution.DoesNotExist:
            return fail("Institution no longer exists.", status=404)

        created = []
        failed = []
        seen_emails: set[str] = set()
        seen_user_codes: set[str] = set()

        for index, row in enumerate(rows):
            serializer = BulkCreateStudentRowSerializer(
                data=row,
                context={
                    "institution": institution,
                    "seen_emails": seen_emails,
                    "seen_user_codes": seen_user_codes,
                },
            )
            if not serializer.is_valid():
                failed.append({
                    "row": index,
                    "email": row.get("email", "") if isinstance(row, dict) else "",
                    "error": _first_error_message(serializer.errors),
                })
                continue

            with transaction.atomic():
                user = serializer.save()
                publish_event(
                    "user.registered",
                    tenant_id=str(user.tenant_id),
                    payload={
                        "user_code": user.user_code,
                        "role": user.role,
                        "department": serializer.validated_data["department"],
                        "batch": serializer.validated_data["batch"],
                        "semester": serializer.validated_data["semester"],
                    },
                )
            seen_emails.add(user.email)
            seen_user_codes.add(user.user_code)
            created.append({"row": index, "email": user.email, "user_code": user.user_code})

        return ok(
            {"created": created, "failed": failed},
            message=f"{len(created)} student(s) created, {len(failed)} failed.",
            status=201,
        )


def _first_error_message(errors: dict) -> str:
    """Flatten a DRF errors dict down to one human-readable string for a
    bulk-row failure entry (the UI shows one error string per failed row,
    not a nested field-by-field structure)."""
    for value in errors.values():
        if isinstance(value, list) and value:
            return str(value[0])
        return str(value)
    return "Invalid row."
```

- [ ] **Step 4: Wire the URL**

In `services/auth-service/accounts/urls.py`, add `UserBulkCreateView` to the import (alphabetical, after `RegisterView` and before `UserAdminView` per the existing alpha ordering — actually insert after `UserAdminView` reads awkwardly; match existing list ordering by inserting after `UserAdminView` import), and add the route immediately after `users`:

```python
from accounts.views import (
    InstitutionView,
    LoginView,
    MeView,
    MyProfileView,
    PlatformAdminView,
    PlatformInstitutionView,
    RefreshView,
    RegisterView,
    UserAdminView,
    UserBulkCreateView,
    UserByCodeView,
    UserProfileView,
)
```

```python
    path("users", UserAdminView.as_view(), name="auth-users"),
    path("users/bulk/", UserBulkCreateView.as_view(), name="auth-users-bulk"),
    path("users/by-code/", UserByCodeView.as_view(), name="auth-user-by-code"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd services/auth-service && python -m pytest accounts/tests/test_bulk_create.py -v`
Expected: PASS (9 tests)

- [ ] **Step 6: Run the full auth-service test suite to check for regressions**

Run: `cd services/auth-service && python -m pytest -v`
Expected: PASS (all existing tests still pass)

- [ ] **Step 7: Commit**

```bash
git add services/auth-service/accounts/views.py services/auth-service/accounts/urls.py services/auth-service/accounts/tests/test_bulk_create.py
git commit -m "feat(auth-service): add POST /api/v1/auth/users/bulk/ for bulk student creation"
```

---

## Task 3: student-service — StudentProfile uniqueness constraint

**Files:**
- Modify: `services/student-service/students/models.py`
- Create: `services/student-service/students/migrations/0002_studentprofile_unique_tenant_user_code.py` (generated via `makemigrations`)
- Test: `services/student-service/students/tests/test_models.py`

**Interfaces:**
- Produces: `StudentProfile.Meta.unique_together = [("tenant_id", "user_code")]` — Task 4's consumer relies on this for `get_or_create` to be a true idempotency guard.

- [ ] **Step 1: Write the failing test**

Create `services/student-service/students/tests/test_models.py`:

```python
"""StudentProfile model constraints."""

import uuid

import pytest
from django.db import IntegrityError, transaction
from students.models import StudentProfile

pytestmark = pytest.mark.django_db


def test_user_code_unique_per_tenant():
    tenant_id = uuid.uuid4()
    StudentProfile.objects.create(
        tenant_id=tenant_id, user_code="STU-1", department="CS", batch="2026", semester=1
    )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            StudentProfile.objects.create(
                tenant_id=tenant_id, user_code="STU-1", department="EE", batch="2026", semester=1
            )


def test_same_user_code_allowed_across_different_tenants():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    StudentProfile.objects.create(
        tenant_id=tenant_a, user_code="STU-1", department="CS", batch="2026", semester=1
    )
    # No exception: user_code uniqueness is per-tenant, not global.
    StudentProfile.objects.create(
        tenant_id=tenant_b, user_code="STU-1", department="CS", batch="2026", semester=1
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/student-service && python -m pytest students/tests/test_models.py -v`
Expected: FAIL on `test_user_code_unique_per_tenant` — no `IntegrityError` raised (no constraint exists yet).

- [ ] **Step 3: Add the constraint**

In `services/student-service/students/models.py`, add a `Meta` class to `StudentProfile` (after the `cgpa`/`created_at` fields, before `def __str__`):

```python
    class Meta:
        unique_together = [("tenant_id", "user_code")]
```

- [ ] **Step 4: Generate the migration**

Run: `cd services/student-service && python manage.py makemigrations students`
Expected: creates `students/migrations/0002_studentprofile_unique_tenant_user_code.py` (or similarly auto-named) adding the `unique_together` constraint. Verify the generated file only contains an `AlterUniqueTogether` operation — no unrelated changes.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/student-service && python -m pytest students/tests/test_models.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add services/student-service/students/models.py services/student-service/students/migrations/ services/student-service/students/tests/test_models.py
git commit -m "feat(student-service): enforce unique (tenant_id, user_code) on StudentProfile"
```

---

## Task 4: student-service — user.registered consumer

**Files:**
- Create: `services/student-service/students/consumers.py`
- Create: `services/student-service/students/management/__init__.py`
- Create: `services/student-service/students/management/commands/__init__.py`
- Create: `services/student-service/students/management/commands/consume_events.py`
- Test: `services/student-service/students/tests/test_consumers.py`

**Interfaces:**
- Consumes: `students.models.StudentProfile` (Task 3, now with the unique constraint), `suerp_common.inbox.idempotent`, `suerp_common.events.make_consumer`.
- Produces: `students.consumers.handle_user_registered(event: dict) -> None`, `students.consumers.dispatch(event: dict) -> None` — same fan-out shape as `hostel.consumers.dispatch`, even though today there's only one routing key, so a second event type can be added later without restructuring.

- [ ] **Step 1: Write the failing tests**

Create `services/student-service/students/tests/test_consumers.py`:

```python
"""user.registered consumer — creates StudentProfile for role=student,
ignores every other role, and is idempotent under redelivery."""

import uuid

import pytest
from students.consumers import dispatch, handle_user_registered
from students.models import StudentProfile
from suerp_common.inbox import ProcessedEvent

pytestmark = pytest.mark.django_db


def _event(event_id=None, role="student", tenant_id=None, user_code="STU-1",
           department="CS", batch="2026", semester=2):
    return {
        "event_id": str(event_id or uuid.uuid4()),
        "type": "user.registered",
        "tenant_id": str(tenant_id or uuid.uuid4()),
        "payload": {
            "user_code": user_code,
            "role": role,
            "department": department,
            "batch": batch,
            "semester": semester,
        },
    }


def test_creates_student_profile_for_student_role():
    event = _event(role="student", user_code="STU-42", department="EE", batch="2027", semester=3)

    handle_user_registered(event)

    profile = StudentProfile.all_objects.get(tenant_id=event["tenant_id"], user_code="STU-42")
    assert profile.department == "EE"
    assert profile.batch == "2027"
    assert profile.semester == 3
    assert profile.cgpa == 0


def test_ignores_non_student_roles():
    event = _event(role="warden", user_code="WARD-1")

    handle_user_registered(event)

    assert not StudentProfile.all_objects.filter(user_code="WARD-1").exists()


def test_idempotent_on_replay_of_same_event_id():
    event = _event(event_id="11111111-1111-1111-1111-111111111111", user_code="STU-1")

    handle_user_registered(event)
    handle_user_registered(event)  # same event_id delivered twice

    assert StudentProfile.all_objects.filter(user_code="STU-1", tenant_id=event["tenant_id"]).count() == 1
    assert ProcessedEvent.objects.filter(event_id=event["event_id"]).count() == 1


def test_get_or_create_guards_against_distinct_event_ids_same_user_code():
    # Two genuinely different events (e.g. a raced double-publish) targeting
    # the same (tenant_id, user_code) must still yield exactly one profile.
    tenant_id = uuid.uuid4()
    event_1 = _event(tenant_id=tenant_id, user_code="STU-9")
    event_2 = _event(tenant_id=tenant_id, user_code="STU-9")

    handle_user_registered(event_1)
    handle_user_registered(event_2)

    assert StudentProfile.all_objects.filter(tenant_id=tenant_id, user_code="STU-9").count() == 1


def test_dispatch_routes_user_registered_to_handler():
    event = _event(user_code="STU-DISPATCH")

    dispatch(event)

    assert StudentProfile.all_objects.filter(user_code="STU-DISPATCH").exists()


def test_dispatch_ignores_unknown_event_type(caplog):
    event = _event(user_code="STU-UNKNOWN")
    event["type"] = "some.other.event"

    dispatch(event)  # must not raise

    assert not StudentProfile.all_objects.filter(user_code="STU-UNKNOWN").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/student-service && python -m pytest students/tests/test_consumers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'students.consumers'`

- [ ] **Step 3: Write the consumer**

Create `services/student-service/students/consumers.py`:

```python
"""user.registered consumer — the async half of bulk/single student creation.

auth-service creates the User row synchronously (see
services/auth-service/accounts/views.py:UserBulkCreateView /
UserAdminView / RegisterView) and publishes user.registered for every role,
not just students. This consumer reacts to that event and creates the
matching StudentProfile — but only when payload["role"] == "student"; every
other role's registration is a silent no-op here, since student-service has
nothing to do with wardens/faculty/etc.

Follows the same three points as the reference consumer pattern in
services/hostel-service/hostel/consumers.py:

1. @idempotent (suerp_common.inbox) outermost — at-least-once delivery means
   duplicates happen.
2. Tenant resolved explicitly from event["tenant_id"], StudentProfile.all_objects
   used (never the tenant-scoped StudentProfile.objects) — this consumer runs as
   a standalone process (manage.py consume_events), never inside a Django
   request, so there's no ambient tenant for the auto-scoping TenantManager.
3. get_or_create on (tenant_id, user_code) as a second idempotency layer,
   beyond @idempotent's event_id tracking — guards against two distinct
   events (different event_id) that both target the same student, which
   @idempotent alone cannot catch. Relies on the unique_together constraint
   added in students/models.py.
"""

import logging

from django.db import transaction
from students.models import StudentProfile
from suerp_common.inbox import idempotent

logger = logging.getLogger(__name__)


@idempotent
def handle_user_registered(event: dict) -> None:
    """Handle user.registered: create a StudentProfile iff role == student."""
    payload = event["payload"]
    if payload.get("role") != "student":
        return

    tenant_id = event["tenant_id"]
    with transaction.atomic():
        StudentProfile.all_objects.get_or_create(
            tenant_id=tenant_id,
            user_code=payload["user_code"],
            defaults={
                "department": payload.get("department", ""),
                "batch": payload.get("batch", ""),
                "semester": payload.get("semester", 1),
            },
        )


def dispatch(event: dict) -> None:
    """Route an event to its handler by event['type'].

    Only one routing key today (user.registered), but kept as a dispatcher
    — not a bare handler reference — for the same reason
    hostel.consumers.dispatch is: a second event type can be added later
    without restructuring the consume_events command.
    """
    handlers = {
        "user.registered": handle_user_registered,
    }
    handler = handlers.get(event["type"])
    if handler is None:
        logger.warning("No handler registered for event type=%s", event["type"])
        return
    handler(event)
```

- [ ] **Step 4: Wire the management command**

Create `services/student-service/students/management/__init__.py` (empty file).

Create `services/student-service/students/management/commands/__init__.py` (empty file).

Create `services/student-service/students/management/commands/consume_events.py`:

```python
"""``manage.py consume_events`` — run student-service's event consumer loop.

Binds a durable queue (``student.profile.sync``) to ``user.registered`` and
blocks, dispatching each delivered message to ``students.consumers.dispatch``.
Intended to run as a long-lived process, separate from the request-serving
Django process — mirrors
services/hostel-service/hostel/management/commands/consume_events.py.
"""

from django.core.management.base import BaseCommand
from students.consumers import dispatch
from suerp_common.events import make_consumer


class Command(BaseCommand):
    help = "Consume user.registered and create matching StudentProfile rows (blocking loop)."

    def handle(self, *args, **options):
        make_consumer(
            queue="student.profile.sync",
            routing_keys=["user.registered"],
            handler=dispatch,
        )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd services/student-service && python -m pytest students/tests/test_consumers.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Run the full student-service test suite to check for regressions**

Run: `cd services/student-service && python -m pytest -v`
Expected: PASS (all existing tests still pass)

- [ ] **Step 7: Commit**

```bash
git add services/student-service/students/consumers.py services/student-service/students/management services/student-service/students/tests/test_consumers.py
git commit -m "feat(student-service): consume user.registered to create StudentProfile async"
```

---

## Task 5: infra — wire student-service consumer in docker-compose

**Files:**
- Modify: `infra/docker-compose.yml`

**Interfaces:**
- Consumes: the `student-consumer` command `python manage.py consume_events` created in Task 4.
- Produces: a new `student-consumer` compose service, profile `["full"]` (matching the existing `student-service` web entry's profile — see [[su-erp-local-cpu-constraint]], consumers are opt-in infra like the rest of student-service already is).

- [ ] **Step 1: Add build/env anchors to the existing `student-service` block**

In `infra/docker-compose.yml`, find the existing `student-service` block (currently around line 262-271):

```yaml
  student-service:
    <<: *django-svc
    container_name: student-service
    profiles: ["full"]
    build:
      context: ..
      dockerfile: services/student-service/Dockerfile
    environment:
      <<: *django-env
      DATABASE_URL: postgres://suerp:suerp@pgbouncer:6432/student
    command: *web-command
```

Replace with (adding `&student-build`/`&student-env` anchors, matching the `hostel-service` block's shape exactly — no other line changes):

```yaml
  student-service:
    <<: *django-svc
    container_name: student-service
    profiles: ["full"]
    build: &student-build
      context: ..
      dockerfile: services/student-service/Dockerfile
    environment: &student-env
      <<: *django-env
      DATABASE_URL: postgres://suerp:suerp@pgbouncer:6432/student
    command: *web-command
```

- [ ] **Step 2: Add the `student-consumer` service entry**

In the "Event consumers" section (after the existing `notification-consumer` block, before `transport-consumer`, keeping alphabetical order — `student` sorts after `notification` and before `transport`):

```yaml
  student-consumer:
    <<: *django-svc
    container_name: student-consumer
    profiles: ["full"]
    build: *student-build
    environment: *student-env
    command: python manage.py consume_events
```

- [ ] **Step 3: Validate the compose file parses**

Run: `docker compose -f infra/docker-compose.yml config --quiet`
Expected: no output, exit code 0 (confirms YAML anchors resolve and the file is structurally valid).

- [ ] **Step 4: Commit**

```bash
git add infra/docker-compose.yml
git commit -m "chore(infra): wire student-consumer for user.registered event processing"
```

---

## Task 6: frontend — sidebar entry

**Files:**
- Modify: `frontend/su-erp-web/src/components/DashboardShell.tsx`

**Interfaces:**
- Produces: a new nav item at `NAV.admin`, so `/admin/students/new` (built in Task 7) is reachable from the sidebar.

- [ ] **Step 1: Add the nav entry**

In `frontend/su-erp-web/src/components/DashboardShell.tsx`, the `admin` array currently reads (line 50-53):

```typescript
  admin: [
    { label: "Overview", href: "/admin", icon: LayoutDashboard },
    { label: "Profile", href: "/admin/profile", icon: User },
  ],
```

Change to:

```typescript
  admin: [
    { label: "Overview", href: "/admin", icon: LayoutDashboard },
    { label: "Add Students", href: "/admin/students/new", icon: GraduationCap },
    { label: "Profile", href: "/admin/profile", icon: User },
  ],
```

`GraduationCap` is already imported (line 9, used by the `faculty` nav array) — no import change needed.

- [ ] **Step 2: Confirm no existing test breaks**

Run: `cd frontend/su-erp-web && npx jest DashboardShell 2>&1 || true`
Expected: either no test file matches (nothing to break) or existing tests pass — there is no dedicated `DashboardShell.test.tsx` in this repo today per the earlier `find`, so this step just guards against a hidden one.

- [ ] **Step 3: Commit**

```bash
git add frontend/su-erp-web/src/components/DashboardShell.tsx
git commit -m "feat(admin-ui): add Add Students sidebar entry"
```

---

## Task 7: frontend — sample CSV + `/admin/students/new` page

**Files:**
- Create: `frontend/su-erp-web/public/sample-student-upload.csv`
- Create: `frontend/su-erp-web/src/app/(dashboard)/admin/students/new/page.tsx`
- Test: `frontend/su-erp-web/src/app/(dashboard)/admin/students/new/students-new.test.tsx`

**Interfaces:**
- Consumes: `@/components/DashboardShell` (`DashboardShell`, Task 6), `@/lib/api` (`api.post`, `ApiError` — existing, no change), `@/components/ui/{Card,CardBody,CardHeader,Field,Input,Select,Button,Alert,Table,TBody,TD,TH,THead,HeaderRow,Row}` (existing, no change).
- Produces: default export `AddStudentsPage` mounted at route `/admin/students/new`. Both `AddStudentForm` and `BulkStudentUpload` POST to `/api/v1/auth/users/bulk/` — the single-add form sends `{"rows": [oneRow]}`, matching Task 2's endpoint exactly (no separate single-create endpoint, per the design's Architecture section).

- [ ] **Step 1: Create the sample CSV**

Create `frontend/su-erp-web/public/sample-student-upload.csv`:

```
email,user_code,password,department,batch,semester
jane.doe@example.com,STU-1001,ChangeMe123,Computer Science,2026,1
```

- [ ] **Step 2: Write the failing test**

Create `frontend/su-erp-web/src/app/(dashboard)/admin/students/new/students-new.test.tsx`. First inspect the sibling `admin/admin.test.tsx` for this repo's exact mocking conventions (auth guard, `api` module) before writing — reuse its `jest.mock` setup for `@/lib/useAuthGuard`, `@/lib/session`, and `@/lib/api` verbatim, adapting only the assertions below:

```typescript
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AddStudentsPage from "./page";
import { api } from "@/lib/api";

// Mirror the mocking setup from ../../admin.test.tsx: useAuthGuard resolves
// ready with an admin claim, fetchMe/institution calls resolve harmlessly,
// and api.post/api.get are jest.fn()s this file controls per test.
jest.mock("@/lib/useAuthGuard", () => ({
  useAuthGuard: () => ({ ready: true, claims: { sub: "ADMIN-1", role: "admin", tenant: "t1" } }),
}));
jest.mock("@/lib/session", () => ({
  fetchMe: () => Promise.resolve({ email: "admin@example.com" }),
}));
jest.mock("@/lib/api", () => ({
  api: { get: jest.fn(), post: jest.fn() },
  ApiError: class ApiError extends Error {},
}));

const mockedApi = api as jest.Mocked<typeof api>;

beforeEach(() => {
  jest.clearAllMocks();
  mockedApi.get.mockResolvedValue({ name: "Test Institution", slug: "test", id: "t1" });
});

describe("AddStudentsPage — single-student form", () => {
  it("submits one row wrapped in a rows array", async () => {
    mockedApi.post.mockResolvedValueOnce({
      created: [{ row: 0, email: "new@example.com", user_code: "STU-1" }],
      failed: [],
    });

    render(<AddStudentsPage />);

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText(/user code/i), { target: { value: "STU-1" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "s3cur3pass" } });
    fireEvent.change(screen.getByLabelText(/department/i), { target: { value: "CS" } });
    fireEvent.change(screen.getByLabelText(/batch/i), { target: { value: "2026" } });
    fireEvent.change(screen.getByLabelText(/semester/i), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: /add student/i }));

    await waitFor(() => expect(mockedApi.post).toHaveBeenCalledWith(
      "/api/v1/auth/users/bulk/",
      { rows: [expect.objectContaining({ email: "new@example.com", user_code: "STU-1" })] },
    ));
    expect(await screen.findByText(/created/i)).toBeInTheDocument();
  });
});

describe("AddStudentsPage — bulk CSV upload", () => {
  function csvFile(contents: string) {
    return new File([contents], "students.csv", { type: "text/csv" });
  }

  it("parses a CSV and posts all rows, then renders per-row results", async () => {
    mockedApi.post.mockResolvedValueOnce({
      created: [{ row: 0, email: "a@example.com", user_code: "STU-A" }],
      failed: [{ row: 1, email: "b@example.com", error: "A user with this email already exists." }],
    });

    render(<AddStudentsPage />);

    const csv = [
      "email,user_code,password,department,batch,semester",
      "a@example.com,STU-A,s3cur3pass,CS,2026,1",
      "b@example.com,STU-B,s3cur3pass,EE,2026,2",
    ].join("\n");

    const input = screen.getByLabelText(/csv file/i);
    fireEvent.change(input, { target: { files: [csvFile(csv)] } });

    await waitFor(() => expect(mockedApi.post).toHaveBeenCalledWith(
      "/api/v1/auth/users/bulk/",
      { rows: [
        expect.objectContaining({ email: "a@example.com", user_code: "STU-A" }),
        expect.objectContaining({ email: "b@example.com", user_code: "STU-B" }),
      ] },
    ));

    expect(await screen.findByText("a@example.com")).toBeInTheDocument();
    expect(await screen.findByText("b@example.com")).toBeInTheDocument();
    expect(screen.getByText(/already exists/i)).toBeInTheDocument();
  });

  it("rejects a CSV with the wrong header before making any request", async () => {
    render(<AddStudentsPage />);

    const badCsv = "name,code\nJane,STU-1";
    const input = screen.getByLabelText(/csv file/i);
    fireEvent.change(input, { target: { files: [csvFile(badCsv)] } });

    expect(await screen.findByText(/unexpected header/i)).toBeInTheDocument();
    expect(mockedApi.post).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend/su-erp-web && npx jest students-new -v`
Expected: FAIL — `Cannot find module './page'`

- [ ] **Step 4: Write the page**

Create `frontend/su-erp-web/src/app/(dashboard)/admin/students/new/page.tsx`:

```typescript
"use client";

import { useCallback, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { api, ApiError } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

const CSV_HEADER = "email,user_code,password,department,batch,semester";

interface StudentRow {
  email: string;
  user_code: string;
  password: string;
  department: string;
  batch: string;
  semester: number;
}

interface BulkCreateResult {
  created: { row: number; email: string; user_code: string }[];
  failed: { row: number; email: string; error: string }[];
}

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

/** Minimal CSV parser for the fixed, known-safe student-upload column set —
 * no quoted-field support, since the columns are all plain tokens
 * (email/code/password/free-text department/batch, integer semester). */
function parseStudentCsv(text: string): StudentRow[] {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter((l) => l.length > 0);
  if (lines.length === 0) throw new Error("CSV file is empty.");

  const header = lines[0];
  if (header !== CSV_HEADER) {
    throw new Error(`Unexpected header. Expected: ${CSV_HEADER}`);
  }

  return lines.slice(1).map((line) => {
    const [email, user_code, password, department, batch, semester] = line.split(",").map((c) => c.trim());
    return {
      email,
      user_code,
      password,
      department,
      batch,
      semester: Number(semester) || 1,
    };
  });
}

async function submitRows(rows: StudentRow[]): Promise<BulkCreateResult> {
  return api.post<BulkCreateResult>("/api/v1/auth/users/bulk/", { rows });
}

function AddStudentForm({ onResult }: { onResult: (r: BulkCreateResult) => void }) {
  const [email, setEmail] = useState("");
  const [userCode, setUserCode] = useState("");
  const [password, setPassword] = useState("");
  const [department, setDepartment] = useState("");
  const [batch, setBatch] = useState("");
  const [semester, setSemester] = useState("1");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const onSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      setSubmitting(true);
      setError(null);
      setSuccess(null);
      try {
        const result = await submitRows([{
          email,
          user_code: userCode,
          password,
          department,
          batch,
          semester: Number(semester) || 1,
        }]);
        onResult(result);
        if (result.failed.length > 0) {
          setError(result.failed[0].error);
        } else {
          setSuccess(`Created ${result.created[0]?.email ?? email}.`);
          setEmail("");
          setUserCode("");
          setPassword("");
          setDepartment("");
          setBatch("");
          setSemester("1");
        }
      } catch (err) {
        setError(errMsg(err));
      } finally {
        setSubmitting(false);
      }
    },
    [email, userCode, password, department, batch, semester, onResult],
  );

  return (
    <Card>
      <CardHeader title="Add one student" />
      <CardBody>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Email" htmlFor="add-student-email">
              <Input id="add-student-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="User code" htmlFor="add-student-code">
              <Input id="add-student-code" required value={userCode} onChange={(e) => setUserCode(e.target.value)} placeholder="e.g. STU001" />
            </Field>
            <Field label="Password" htmlFor="add-student-password">
              <Input id="add-student-password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Field label="Department" htmlFor="add-student-department">
              <Input id="add-student-department" required value={department} onChange={(e) => setDepartment(e.target.value)} />
            </Field>
            <Field label="Batch" htmlFor="add-student-batch">
              <Input id="add-student-batch" required value={batch} onChange={(e) => setBatch(e.target.value)} placeholder="e.g. 2026" />
            </Field>
            <Field label="Semester" htmlFor="add-student-semester">
              <Input id="add-student-semester" type="number" min={1} required value={semester} onChange={(e) => setSemester(e.target.value)} />
            </Field>
          </div>
          {error && <Alert tone="error">{error}</Alert>}
          {success && <Alert tone="success">{success}</Alert>}
          <Button type="submit" loading={submitting}>Add student</Button>
        </form>
      </CardBody>
    </Card>
  );
}

function BulkStudentUpload({ onResult }: { onResult: (r: BulkCreateResult) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const onFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = ""; // allow re-selecting the same file after a failed attempt
      if (!file) return;

      setError(null);
      let rows: StudentRow[];
      try {
        const text = await file.text();
        rows = parseStudentCsv(text);
      } catch (err) {
        setError(errMsg(err));
        return;
      }
      if (rows.length === 0) {
        setError("CSV file has no data rows.");
        return;
      }

      setUploading(true);
      try {
        const result = await submitRows(rows);
        onResult(result);
      } catch (err) {
        setError(errMsg(err));
      } finally {
        setUploading(false);
      }
    },
    [onResult],
  );

  return (
    <Card>
      <CardHeader title="Bulk upload (CSV)" />
      <CardBody>
        <div className="space-y-4">
          <p className="text-[13px] text-muted">
            Columns: <code>{CSV_HEADER}</code>.{" "}
            <a href="/sample-student-upload.csv" className="text-primary underline" download>
              Download sample CSV
            </a>
          </p>
          <Field label="CSV file" htmlFor="bulk-student-csv">
            <input
              id="bulk-student-csv"
              type="file"
              accept=".csv"
              onChange={onFileChange}
              disabled={uploading}
              className="block w-full text-[13px] text-muted file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-primary-fg"
            />
          </Field>
          {uploading && <p className="text-[13px] text-muted">Uploading…</p>}
          {error && <Alert tone="error">{error}</Alert>}
        </div>
      </CardBody>
    </Card>
  );
}

function BulkResultsPanel({ result }: { result: BulkCreateResult | null }) {
  if (result === null) return null;
  return (
    <Card>
      <CardHeader title={`Results: ${result.created.length} created, ${result.failed.length} failed`} />
      <CardBody>
        <p className="mb-3 text-[13px] text-muted">
          Created students&apos; profiles (department/batch/semester) sync in the background — they may take a
          few seconds to appear.
        </p>
        <Table>
          <THead>
            <HeaderRow>
              <TH>Row</TH>
              <TH>Email</TH>
              <TH>Status</TH>
            </HeaderRow>
          </THead>
          <TBody>
            {result.created.map((c) => (
              <Row key={`created-${c.row}`}>
                <TD>{c.row + 1}</TD>
                <TD className="font-medium">{c.email}</TD>
                <TD className="text-success">Created</TD>
              </Row>
            ))}
            {result.failed.map((f) => (
              <Row key={`failed-${f.row}`}>
                <TD>{f.row + 1}</TD>
                <TD className="font-medium">{f.email}</TD>
                <TD className="text-danger">{f.error}</TD>
              </Row>
            ))}
          </TBody>
        </Table>
      </CardBody>
    </Card>
  );
}

function AddStudentsContent() {
  const [result, setResult] = useState<BulkCreateResult | null>(null);

  return (
    <div className="space-y-6">
      <AddStudentForm onResult={setResult} />
      <BulkStudentUpload onResult={setResult} />
      <BulkResultsPanel result={result} />
    </div>
  );
}

export default function AddStudentsPage() {
  return (
    <DashboardShell title="Add Students" role="admin">
      <AddStudentsContent />
    </DashboardShell>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend/su-erp-web && npx jest students-new -v`
Expected: PASS (3 tests). If `Alert`/`Table` component prop names (`tone`, etc.) or `text-success`/`text-danger` utility classes don't match this repo's actual `Alert`/`Table`/CSS-token conventions, adjust to match — re-check `@/components/ui/Alert.tsx` and the existing `StatusPill` component's tone-to-class mapping in `admin/page.tsx` if `text-success`/`text-danger` don't exist as utilities, and use whatever token this repo's `StatusPill`/`Alert` already use for success/error color.

- [ ] **Step 6: Run the full frontend test suite to check for regressions**

Run: `cd frontend/su-erp-web && npx jest`
Expected: PASS (all existing tests still pass)

- [ ] **Step 7: Commit**

```bash
git add frontend/su-erp-web/public/sample-student-upload.csv frontend/su-erp-web/src/app/\(dashboard\)/admin/students/new/
git commit -m "feat(admin-ui): add /admin/students/new page with single-add form and CSV bulk upload"
```

---

## Task 8: manual end-to-end verification

**Files:** none (verification only).

- [ ] **Step 1: Bring up the stack with the `full` profile** (student-service and its new consumer are `profiles: ["full"]`, per [[su-erp-local-cpu-constraint]] — the default profile won't start them)

Run: `docker compose -f infra/docker-compose.yml --profile full up -d --build gateway auth-service student-service student-consumer rabbitmq`
Expected: all five containers reach a running/healthy state (`docker compose -f infra/docker-compose.yml ps`).

- [ ] **Step 2: Log in as an admin and open the new page**

In a browser: log in as an existing admin user for a seeded institution, navigate to the sidebar's new "Add Students" link, confirm it lands on `/admin/students/new` and renders both the single-add form and the CSV upload widget.

- [ ] **Step 3: Exercise the single-add form**

Fill in a new email/user_code/password/department/batch/semester, submit, confirm the success alert and that the row appears in the results table as "Created."

- [ ] **Step 4: Exercise CSV bulk upload with a mixed-outcome file**

Download the sample CSV, edit it to add 2-3 rows including one duplicate of the just-created user, upload it, confirm the results table shows the correct created/failed split with the duplicate's error message.

- [ ] **Step 5: Confirm the StudentProfile arrived asynchronously**

Run: `docker compose -f infra/docker-compose.yml exec student-service python manage.py shell -c "from students.models import StudentProfile; print(list(StudentProfile.all_objects.values('user_code','department','batch','semester')))"`
Expected: the newly created students' profiles appear with the department/batch/semester submitted in the form/CSV, confirming the consumer processed the events end-to-end.

- [ ] **Step 6: Check consumer logs for errors**

Run: `docker compose -f infra/docker-compose.yml logs student-consumer --tail 50`
Expected: no unhandled exceptions/tracebacks; messages were acked (no repeated redelivery churn).

No commit for this task — it's manual verification, not a code change.

---

## Self-Review Notes

- **Spec coverage:** Architecture (sync auth-service endpoint + async student-service consumer) → Tasks 1-2, 4; role-hardcoded student-only endpoint → Task 2; partial-failure semantics → Task 2 tests; StudentProfile idempotency/no uniqueness-failure-mode claim → Task 3 (constraint) + Task 4 (get_or_create); frontend page with both forms sharing the bulk endpoint → Task 7; sidebar entry → Task 6; sample CSV → Task 7; docker-compose wiring → Task 5; manual e2e → Task 8. All "Changes by service" and "Testing" bullets from the design doc are covered.
- **Placeholder scan:** none found — every step has literal code/commands.
- **Type consistency:** `BulkCreateResult` (frontend) matches the auth-service response shape (`created`/`failed` arrays with `row`/`email`/`user_code`/`error` fields) exactly across Task 2 and Task 7. `StudentRow` fields match `BulkCreateStudentRowSerializer` fields exactly (Task 1 vs Task 7). Consumer payload keys (`department`, `batch`, `semester`, `role`, `user_code`) match between Task 2's `publish_event` call and Task 4's `handle_user_registered` read.
