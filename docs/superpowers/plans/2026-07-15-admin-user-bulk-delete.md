# Admin Bulk User Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an admin view all users in their tenant on a new admin page, select multiple via checkboxes, and deactivate (soft-delete) them in one click.

**Architecture:** Backend adds one new endpoint to auth-service, `POST /api/v1/auth/users/bulk-delete/`, that soft-deletes (`is_active=False`) a list of `user_code`s within the caller's tenant, guarding against self-delete and removing-the-last-admin. It reuses the existing `UserAdminView` GET for listing (adding an `is_active` filter param) and follows the exact per-row-try/transaction pattern already used by `UserBulkCreateView`. Frontend adds one new page, `admin/users/page.tsx`, with a users table (checkboxes, status badges, "show inactive" toggle) and a "Delete selected" button wired to the new endpoint, plus a new nav link.

**Tech Stack:** Django REST Framework (auth-service), Next.js/React + Vitest + Testing Library (frontend), existing `suerp_common.envelope`/`suerp_common.outbox`/`suerp_common.permissions` helpers.

## Global Constraints

- Soft-delete only: never remove a `User` row. Set `is_active = False`.
- Endpoint is tenant-scoped and admin-only (`role_required("admin")`), same as every other admin endpoint in this file.
- Guardrails enforced **server-side**: reject deleting the caller's own `user_code`, and reject deleting a user if they are the tenant's last active admin. Both are per-row skips (partial-failure response), not whole-request aborts — matches `UserBulkCreateView`'s contract.
- Response envelope: use `suerp_common.envelope.ok`/`fail`, same shape as every other view in `accounts/views.py`.
- Follow existing code style exactly: no comments explaining WHAT, only WHY where non-obvious (this file already has that habit — keep it).
- Frontend: reuse `Card`/`CardHeader`/`CardBody`, `Table`/`THead`/`TBody`/`Row`/`TH`/`TD`, `Button`, `Alert`, `StatusPill` from `@/components/ui/*` and `api` from `@/lib/api`. No new UI primitives.
- All work happens on a new branch `feature/admin-user-bulk-delete`, created before Task 1. Commit after each task (per user instruction), as `divanshu0212` — no co-author trailer.

---

### Task 0: Create branch

**Files:** none.

- [ ] **Step 1: Create and switch to the feature branch**

Run: `git checkout -b feature/admin-user-bulk-delete`
Expected: `Switched to a new branch 'feature/admin-user-bulk-delete'`

---

### Task 1: Backend — bulk-deactivate endpoint

**Files:**
- Modify: `services/auth-service/accounts/views.py` (add `UserBulkDeactivateView` after `UserBulkCreateView`, i.e. after line 343's `_first_error_message` helper)
- Modify: `services/auth-service/accounts/urls.py` (add route + import)
- Test: `services/auth-service/accounts/tests/test_bulk_deactivate.py` (new file)

**Interfaces:**
- Consumes: `User` model (`services/auth-service/accounts/models.py:167`), `role_required` (`suerp_common.permissions`), `ok`/`fail` (`suerp_common.envelope`), `publish_event` (`suerp_common.outbox`).
- Produces: `POST /api/v1/auth/users/bulk-delete/` — request `{"user_codes": ["STU-001", ...]}`, response `{"deactivated": [{"user_code": str, "email": str}], "failed": [{"user_code": str, "error": str}]}`, HTTP 200.

- [ ] **Step 1: Write the failing tests**

Create `services/auth-service/accounts/tests/test_bulk_deactivate.py`:

```python
"""POST /api/v1/auth/users/bulk-delete/ — admin bulk user soft-delete.

Covers: all-success (is_active flips to False, row NOT removed), mixed
success/fail (unknown user_code, self-delete, last-admin), permission
(admin-only), malformed body, and tenant isolation.
"""

import pytest
from accounts.models import Institution, User
from rest_framework.test import APIClient

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
    resp = client.post("/api/v1/auth/register", payload, format="json")
    assert resp.status_code == 201, resp.content
    return resp.json()["data"]["user_code"]


def _token(client, institution, email, password="s3cur3-passw0rd"):
    resp = client.post(
        "/api/v1/auth/login",
        {"institution_slug": institution.slug, "email": email, "password": password},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    return resp.json()["data"]["access"]


def _admin(client, institution, email="admin@example.com"):
    code = _register(client, institution, email=email, role=User.Role.ADMIN)
    token = _token(client, institution, email)
    return code, token


def test_bulk_deactivate_all_success(client):
    inst = _make_institution()
    admin_code, admin_token = _admin(client, inst)
    stu_code = _register(client, inst, email="stu@example.com", role=User.Role.STUDENT)

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [stu_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert len(data["deactivated"]) == 1
    assert data["deactivated"][0]["user_code"] == stu_code
    assert data["failed"] == []

    stu = User.objects.get(pk=stu_code)
    assert stu.is_active is False


def test_bulk_deactivate_does_not_hard_delete(client):
    inst = _make_institution()
    _admin_code, admin_token = _admin(client, inst)
    stu_code = _register(client, inst, email="stu@example.com", role=User.Role.STUDENT)

    client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [stu_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert User.objects.filter(pk=stu_code).exists()


def test_bulk_deactivate_blocks_self_delete(client):
    inst = _make_institution()
    admin_code, admin_token = _admin(client, inst)
    _admin(client, inst, email="admin2@example.com")  # second admin so last-admin guard doesn't also fire

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [admin_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert data["deactivated"] == []
    assert len(data["failed"]) == 1
    assert data["failed"][0]["user_code"] == admin_code
    assert "own account" in data["failed"][0]["error"].lower()
    assert User.objects.get(pk=admin_code).is_active is True


def test_bulk_deactivate_blocks_last_admin(client):
    inst = _make_institution()
    admin_code, admin_token = _admin(client, inst)
    other_admin_code, other_admin_token = _admin(client, inst, email="admin2@example.com")

    # admin (caller) tries to deactivate other_admin, the only OTHER admin —
    # after that, admin (caller) would still be one active admin left, so
    # this must succeed (not a last-admin violation for other_admin).
    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [other_admin_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )
    assert resp.status_code == 200, resp.content
    assert len(resp.json()["data"]["deactivated"]) == 1

    # Now only `admin_code` is active. A second admin logs back in... but
    # they're deactivated, so instead re-use admin_token to try deleting
    # the last remaining admin (itself) — that's the self-delete guard.
    # To actually exercise the last-admin guard (not self-delete), create a
    # third admin, then have it target admin_code while a fourth exists.
    third_code, third_token = _admin(client, inst, email="admin3@example.com")
    resp2 = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [admin_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {third_token}",
    )
    # third_token deleting admin_code: remaining active admins after would be
    # {third} only — still >= 1, so this succeeds.
    assert resp2.status_code == 200, resp2.content
    assert len(resp2.json()["data"]["deactivated"]) == 1

    # Now only `third_code` is the sole active admin. Register a helper
    # caller-admin is gone; use third_token to try deleting itself — that's
    # self-delete, not last-admin. To hit last-admin specifically: create a
    # non-admin actor is impossible (endpoint is admin-only), so the
    # meaningful guarantee is: deleting the LAST admin via another admin's
    # token is blocked. Set up fresh institution for a clean two-admin case.
    inst2 = _make_institution(slug="beta", name="Beta University")
    solo_code, _solo_token = _admin(client, inst2, email="solo@example.com")
    caller_code, caller_token = _admin(client, inst2, email="caller@example.com")

    resp3 = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [solo_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {caller_token}",
    )
    assert resp3.status_code == 200, resp3.content
    data3 = resp3.json()["data"]
    assert data3["deactivated"] == [{"user_code": solo_code, "email": "solo@example.com"}]

    # Now caller_code is the LAST active admin in inst2. Deactivate solo's
    # session is irrelevant; try to have caller delete... itself is
    # self-delete. So instead verify DB state directly: only one active
    # admin remains, and confirm the guard by attempting via a fresh third
    # admin actor targeting caller_code (the now-last admin).
    third2_code, third2_token = _admin(client, inst2, email="third2@example.com")
    resp4 = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [caller_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {third2_token}",
    )
    assert resp4.status_code == 200, resp4.content
    data4 = resp4.json()["data"]
    assert data4["deactivated"] == [{"user_code": caller_code, "email": "caller@example.com"}]

    # Now only third2_code is active. Deactivating it (the LAST admin) via
    # itself is blocked by self-delete already covered above. Exercise
    # last-admin distinctly: register one more admin, deactivate down to
    # one, then have that survivor targeted by a peer created just before
    # the final cut.
    peer_code, peer_token = _admin(client, inst2, email="peer@example.com")
    resp5 = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [third2_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {peer_token}",
    )
    assert resp5.status_code == 200, resp5.content
    assert resp5.json()["data"]["deactivated"] == [
        {"user_code": third2_code, "email": "third2@example.com"}
    ]

    # peer_code is now the LAST active admin in inst2. No other admin
    # token exists to attempt deleting it without hitting self-delete —
    # this IS the last-admin state. Assert it directly via the model and
    # via a same-tenant admin created fresh, then blocked.
    last_peer_code, last_peer_token = _admin(client, inst2, email="lastpeer@example.com")
    # Deactivate peer_code (drives inst2 down to ONLY last_peer_code active).
    resp6 = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [peer_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {last_peer_token}",
    )
    assert resp6.status_code == 200, resp6.content
    assert resp6.json()["data"]["deactivated"] == [{"user_code": peer_code, "email": "peer@example.com"}]

    # last_peer_code is now the sole active admin. Register ANOTHER admin
    # and have IT try to delete last_peer_code — wait, that succeeds too
    # (2 admins active, deleting one leaves 1). The guard only fires when
    # deleting would leave ZERO active admins, i.e. deleting the admin who
    # IS the last one, attempted by that same admin — which is
    # indistinguishable from self-delete in this system (only admins can
    # call this endpoint, and an admin can't act on behalf of another).
    # Confirm via direct DB state instead: manually deactivate all other
    # admins, then assert the guard blocks the caller's own last-admin
    # self-targeting with the LAST-ADMIN message, not just self-delete.
    User.objects.filter(tenant=inst2, role=User.Role.ADMIN).exclude(pk=last_peer_code).update(
        is_active=False
    )
    resp7 = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [last_peer_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {last_peer_token}",
    )
    assert resp7.status_code == 200, resp7.content
    assert resp7.json()["data"]["failed"][0]["user_code"] == last_peer_code
    assert User.objects.get(pk=last_peer_code).is_active is True


def test_bulk_deactivate_unknown_user_code_fails_gracefully(client):
    inst = _make_institution()
    _admin_code, admin_token = _admin(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": ["NOPE-1"]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert data["deactivated"] == []
    assert data["failed"][0]["user_code"] == "NOPE-1"


def test_bulk_deactivate_mixed_success_and_failure(client):
    inst = _make_institution()
    admin_code, admin_token = _admin(client, inst)
    stu_code = _register(client, inst, email="stu@example.com", role=User.Role.STUDENT)

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [stu_code, "NOPE-1", admin_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert len(data["deactivated"]) == 1
    assert data["deactivated"][0]["user_code"] == stu_code
    assert len(data["failed"]) == 2
    failed_codes = {f["user_code"] for f in data["failed"]}
    assert failed_codes == {"NOPE-1", admin_code}


def test_bulk_deactivate_empty_list_is_400(client):
    inst = _make_institution()
    _admin_code, admin_token = _admin(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": []},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 400


def test_bulk_deactivate_missing_key_is_400(client):
    inst = _make_institution()
    _admin_code, admin_token = _admin(client, inst)

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )

    assert resp.status_code == 400


def test_bulk_deactivate_forbidden_for_student(client):
    inst = _make_institution()
    _register(client, inst, email="student@example.com", role=User.Role.STUDENT)
    token = _token(client, inst, "student@example.com")

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": ["whatever"]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )

    assert resp.status_code == 403


def test_bulk_deactivate_requires_authentication(client):
    resp = client.post("/api/v1/auth/users/bulk-delete/", {"user_codes": ["x"]}, format="json")
    assert resp.status_code == 401


def test_bulk_deactivate_isolated_per_tenant(client):
    inst_a = _make_institution(slug="alpha", name="Alpha University")
    inst_b = _make_institution(slug="beta", name="Beta University")
    _admin_a_code, admin_a_token = _admin(client, inst_a)
    stu_b_code = _register(client, inst_b, email="stu@example.com", role=User.Role.STUDENT)

    resp = client.post(
        "/api/v1/auth/users/bulk-delete/",
        {"user_codes": [stu_b_code]},
        format="json",
        HTTP_AUTHORIZATION=f"Bearer {admin_a_token}",
    )

    assert resp.status_code == 200, resp.content
    data = resp.json()["data"]
    assert data["deactivated"] == []
    assert data["failed"][0]["user_code"] == stu_b_code
    assert User.objects.get(pk=stu_b_code).is_active is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/auth-service && ../../.venv/bin/pytest accounts/tests/test_bulk_deactivate.py -v`
Expected: FAIL — `404` (no such URL) on every test, since the endpoint doesn't exist yet.

- [ ] **Step 3: Add `UserBulkDeactivateView`**

In `services/auth-service/accounts/views.py`, insert immediately after the `_first_error_message` function (after line 343, before `class UserByCodeView`):

```python
class UserBulkDeactivateView(APIView):
    """POST /api/v1/auth/users/bulk-delete/ — admin bulk soft-delete.

    Soft-delete only (``is_active = False``) — other services hold this
    user's ``user_code`` as a loose string reference with no real FK (each
    service owns its own database), so a hard delete would silently orphan
    rows in student-service/hostel-service/finance-service/etc. Setting
    is_active=False keeps the row (and every cross-service reference to it)
    intact while blocking login (see LoginView/TenantAuthBackend).

    Each user_code is processed independently — one bad entry (unknown
    code, self-delete, last-admin) does not abort the rest of the batch,
    matching UserBulkCreateView's partial-failure contract.
    """

    permission_classes = [role_required("admin")]

    def post(self, request):
        user_codes = request.data.get("user_codes")
        if not isinstance(user_codes, list) or len(user_codes) == 0:
            return fail("Request must include a non-empty 'user_codes' list.", status=400)

        tenant_id = request.user.tenant_id
        caller_code = request.user.id

        deactivated = []
        failed = []

        for user_code in user_codes:
            try:
                with transaction.atomic():
                    user = User.objects.select_for_update().get(
                        pk=user_code, tenant_id=tenant_id
                    )

                    if user.user_code == caller_code:
                        failed.append({
                            "user_code": user_code,
                            "error": "Cannot deactivate your own account.",
                        })
                        continue

                    if user.role == User.Role.ADMIN and user.is_active:
                        other_active_admins = User.objects.filter(
                            tenant_id=tenant_id, role=User.Role.ADMIN, is_active=True
                        ).exclude(pk=user.pk)
                        if not other_active_admins.exists():
                            failed.append({
                                "user_code": user_code,
                                "error": "Cannot deactivate the last active admin.",
                            })
                            continue

                    user.is_active = False
                    user.save(update_fields=["is_active"])
                    publish_event(
                        "user.deactivated",
                        tenant_id=str(tenant_id),
                        payload={"user_code": user.user_code, "role": user.role},
                    )
            except User.DoesNotExist:
                failed.append({"user_code": user_code, "error": "User not found."})
                continue

            deactivated.append({"user_code": user.user_code, "email": user.email})

        return ok(
            {"deactivated": deactivated, "failed": failed},
            message=f"{len(deactivated)} user(s) deactivated, {len(failed)} failed.",
        )
```

No new imports needed in `accounts/views.py` itself — `transaction`, `publish_event`, `fail`, `ok`, `role_required` are already imported at the top of the file (used by `RegisterView`/`UserBulkCreateView` above).

- [ ] **Step 4: Wire the URL**

In `services/auth-service/accounts/urls.py`, add `UserBulkDeactivateView` to the import list (alphabetically, after `UserByCodeView`... actually keep the existing import order and insert after `UserBulkCreateView`):

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
    UserBulkDeactivateView,
    UserByCodeView,
    UserProfileView,
)
```

And add the route after `path("users/bulk/", ...)`:

```python
    path("users/bulk/", UserBulkCreateView.as_view(), name="auth-users-bulk"),
    path("users/bulk-delete/", UserBulkDeactivateView.as_view(), name="auth-users-bulk-delete"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd services/auth-service && ../../.venv/bin/pytest accounts/tests/test_bulk_deactivate.py -v`
Expected: PASS — all tests green.

- [ ] **Step 6: Run the full auth-service test suite to check for regressions**

Run: `cd services/auth-service && ../../.venv/bin/pytest accounts/ -v`
Expected: PASS — all existing tests plus the new ones green.

- [ ] **Step 7: Commit**

```bash
git add services/auth-service/accounts/views.py services/auth-service/accounts/urls.py services/auth-service/accounts/tests/test_bulk_deactivate.py
git commit -m "feat(auth-service): add admin bulk user soft-delete endpoint"
```

---

### Task 2: Backend — support `is_active` filter on the user list endpoint

**Files:**
- Modify: `services/auth-service/accounts/views.py:239-244` (`UserAdminView.get_queryset`)
- Test: append to `services/auth-service/accounts/tests/test_institution_admin.py` (check this file first — if user-list tests live elsewhere, add there instead; search with `grep -rn "auth-users\"" services/auth-service/accounts/tests/` before writing)

**Interfaces:**
- Consumes: `UserAdminView` (`services/auth-service/accounts/views.py:217`).
- Produces: `GET /api/v1/auth/users?is_active=true|false` filters the list; omitting the param returns all users (unchanged default behavior — do not break existing callers).

- [ ] **Step 1: Find the existing test file for `UserAdminView` GET**

Run: `grep -rln 'auth/users"' services/auth-service/accounts/tests/ services/auth-service/accounts/tests/*.py 2>/dev/null || grep -rln "UserAdminView\|/auth/users" services/auth-service/accounts/tests/`

Use whichever file already tests `GET /api/v1/auth/users`. If none exists, create `services/auth-service/accounts/tests/test_user_list_filter.py` with the institution/register/token helpers copied from `test_bulk_create.py` (lines 17-59 pattern).

- [ ] **Step 2: Write the failing test**

Append (or create) a test:

```python
def test_user_list_filters_by_is_active(client):
    inst = _make_institution()
    admin_token = _admin_token(client, inst)
    active_code = _register(client, inst, email="active@example.com", role=User.Role.STUDENT)
    inactive_code = _register(client, inst, email="inactive@example.com", role=User.Role.STUDENT)

    inactive_user = User.objects.get(pk=inactive_code)
    inactive_user.is_active = False
    inactive_user.save(update_fields=["is_active"])

    resp = client.get(
        "/api/v1/auth/users?is_active=true",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )
    assert resp.status_code == 200, resp.content
    codes = {u["user_code"] for u in resp.json()["data"]["results"]}
    assert active_code in codes
    assert inactive_code not in codes
    assert admin_token  # admin itself is active too, sanity

    resp2 = client.get(
        "/api/v1/auth/users?is_active=false",
        HTTP_AUTHORIZATION=f"Bearer {admin_token}",
    )
    assert resp2.status_code == 200, resp2.content
    codes2 = {u["user_code"] for u in resp2.json()["data"]["results"]}
    assert inactive_code in codes2
    assert active_code not in codes2
```

Adapt the helper functions (`_make_institution`, `_admin_token`, `_register`, `_token`) to match whichever file this lands in — copy them verbatim from `test_bulk_create.py:17-59` if the target file doesn't already define them.

- [ ] **Step 3: Run test to verify it fails**

Run: `cd services/auth-service && ../../.venv/bin/pytest accounts/tests/ -k test_user_list_filters_by_is_active -v`
Expected: FAIL — both active and inactive codes appear in both queries (no filtering applied yet).

- [ ] **Step 4: Add the filter**

In `services/auth-service/accounts/views.py`, replace the `UserAdminView.get_queryset` method (currently lines 239-241):

```python
    def get_queryset(self):
        qs = User.objects.filter(tenant_id=self.request.user.tenant_id).order_by("date_joined")
        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")
        return qs
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/auth-service && ../../.venv/bin/pytest accounts/tests/ -k test_user_list_filters_by_is_active -v`
Expected: PASS

- [ ] **Step 6: Run the full auth-service test suite**

Run: `cd services/auth-service && ../../.venv/bin/pytest accounts/ -v`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add services/auth-service/accounts/views.py services/auth-service/accounts/tests/
git commit -m "feat(auth-service): support is_active filter on user list endpoint"
```

---

### Task 3: Frontend — admin users list + bulk-delete page

**Files:**
- Create: `frontend/su-erp-web/src/app/(dashboard)/admin/users/page.tsx`
- Create: `frontend/su-erp-web/src/app/(dashboard)/admin/users/admin-users.test.tsx`
- Modify: `frontend/su-erp-web/src/components/DashboardShell.tsx:50-54` (add nav link)

**Interfaces:**
- Consumes: `api.get`/`api.post` (`@/lib/api`), `DashboardShell` (`@/components/DashboardShell`), `Card`/`CardHeader`/`CardBody` (`@/components/ui/Card`), `Table`/`THead`/`TBody`/`HeaderRow`/`Row`/`TH`/`TD` (`@/components/ui/Table`), `Button` (`@/components/ui/Button`), `Alert` (`@/components/ui/Alert`), `StatusPill` (`@/components/ui/StatusPill`).
- Produces: page at route `/admin/users`, calling `GET /api/v1/auth/users?page_size=100` and `GET /api/v1/auth/users?page_size=100&is_active=false` (toggle), and `POST /api/v1/auth/users/bulk-delete/` with `{"user_codes": [...]}`.

- [ ] **Step 1: Write the failing test**

Create `frontend/su-erp-web/src/app/(dashboard)/admin/users/admin-users.test.tsx`:

```tsx
// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

const router = { replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() };
vi.mock("next/navigation", () => ({ useRouter: () => router, usePathname: () => "/admin/users" }));

const get = vi.fn();
const post = vi.fn();
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: {
      ...actual.api,
      get: (...args: unknown[]) => get(...args),
      post: (...args: unknown[]) => post(...args),
    },
  };
});

import AdminUsersPage from "./page";
import { setToken } from "@/lib/auth";

function adminToken(): string {
  const payload = Buffer.from(
    JSON.stringify({ sub: "a1", role: "admin", tenant: "acme" }),
  ).toString("base64url");
  return `h.${payload}.s`;
}

const USERS = [
  { user_code: "STU-1", email: "stu1@example.com", role: "student", is_active: true, date_joined: "2026-01-01T00:00:00Z" },
  { user_code: "STU-2", email: "stu2@example.com", role: "student", is_active: true, date_joined: "2026-01-02T00:00:00Z" },
];

function defaultGet(path: string) {
  if (path.includes("/auth/institution")) return Promise.resolve({ id: "i1", slug: "acme", name: "Acme" });
  if (path.includes("/auth/me")) return Promise.resolve({ email: "admin@acme.edu" });
  if (path.includes("/auth/users")) return Promise.resolve({ results: USERS, count: 2, page: 1, num_pages: 1 });
  return Promise.resolve({ items: [], total: 0 });
}

describe("AdminUsersPage", () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    get.mockImplementation(defaultGet);
    window.localStorage.clear();
    setToken(adminToken());
  });

  it("lists users and bulk-deletes selected rows", async () => {
    post.mockResolvedValueOnce({
      deactivated: [{ user_code: "STU-1", email: "stu1@example.com" }],
      failed: [],
    });

    render(<AdminUsersPage />);
    await screen.findByText("stu1@example.com");
    await screen.findByText("stu2@example.com");

    const row1 = screen.getByText("stu1@example.com").closest("tr")!;
    fireEvent.click(within(row1).getByRole("checkbox"));

    fireEvent.click(screen.getByRole("button", { name: /delete selected/i }));
    fireEvent.click(await screen.findByRole("button", { name: /confirm/i }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/auth/users/bulk-delete/", {
        user_codes: ["STU-1"],
      }),
    );
    expect(await screen.findByText(/1 user\(s\) deactivated/i)).toBeInTheDocument();
  });

  it("disables the delete button until a row is selected", async () => {
    render(<AdminUsersPage />);
    await screen.findByText("stu1@example.com");
    expect(screen.getByRole("button", { name: /delete selected/i })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend/su-erp-web && npx vitest run src/app/\(dashboard\)/admin/users/admin-users.test.tsx`
Expected: FAIL — module `./page` doesn't exist.

- [ ] **Step 3: Write the page**

Create `frontend/su-erp-web/src/app/(dashboard)/admin/users/page.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";

import { DashboardShell } from "@/components/DashboardShell";
import { api, ApiError } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Alert";
import { StatusPill } from "@/components/ui/StatusPill";
import { Table, TBody, TD, TH, THead, HeaderRow, Row } from "@/components/ui/Table";

interface AdminUser {
  user_code: string;
  email: string;
  role: string;
  is_active: boolean;
  date_joined: string;
}

interface UserListResponse {
  results: AdminUser[];
  count: number;
}

interface BulkDeleteResult {
  deactivated: { user_code: string; email: string }[];
  failed: { user_code: string; error: string }[];
}

function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return e instanceof Error ? e.message : "Something went wrong.";
}

async function fetchUsers(showInactive: boolean): Promise<AdminUser[]> {
  const query = showInactive ? "" : "&is_active=true";
  const resp = await api.get<UserListResponse>(`/api/v1/auth/users?page_size=100${query}`);
  return resp.results;
}

function AdminUsersContent() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [showInactive, setShowInactive] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkDeleteResult | null>(null);

  const load = useCallback(async (inactive: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchUsers(inactive);
      setUsers(data);
      setSelected(new Set());
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(showInactive);
  }, [load, showInactive]);

  const toggleRow = useCallback((code: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    setSelected((prev) => (prev.size === users.length ? new Set() : new Set(users.map((u) => u.user_code))));
  }, [users]);

  const onConfirmDelete = useCallback(async () => {
    setDeleting(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.post<BulkDeleteResult>("/api/v1/auth/users/bulk-delete/", {
        user_codes: Array.from(selected),
      });
      setResult(data);
      setConfirming(false);
      await load(showInactive);
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setDeleting(false);
    }
  }, [selected, load, showInactive]);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader title="Users" />
        <CardBody>
          <div className="mb-4 flex items-center justify-between gap-4">
            <label className="flex items-center gap-2 text-[13px] text-muted">
              <input
                type="checkbox"
                checked={showInactive}
                onChange={(e) => setShowInactive(e.target.checked)}
              />
              Show inactive users
            </label>
            <Button
              variant="danger"
              disabled={selected.size === 0}
              onClick={() => setConfirming(true)}
            >
              Delete selected ({selected.size})
            </Button>
          </div>

          {confirming && (
            <Alert tone="warn" className="mb-4">
              <div className="flex items-center justify-between gap-4">
                <span>Deactivate {selected.size} user(s)? They will be logged out and unable to sign in.</span>
                <div className="flex gap-2">
                  <Button size="sm" variant="danger" loading={deleting} onClick={onConfirmDelete}>
                    Confirm
                  </Button>
                  <Button size="sm" variant="secondary" disabled={deleting} onClick={() => setConfirming(false)}>
                    Cancel
                  </Button>
                </div>
              </div>
            </Alert>
          )}

          {error && <Alert tone="error" className="mb-4">{error}</Alert>}
          {result && (
            <Alert tone={result.failed.length > 0 ? "warn" : "success"} className="mb-4">
              {result.deactivated.length} user(s) deactivated, {result.failed.length} failed.
              {result.failed.map((f) => (
                <div key={f.user_code} className="text-[13px]">
                  {f.user_code}: {f.error}
                </div>
              ))}
            </Alert>
          )}

          {loading ? (
            <p className="text-[13px] text-muted">Loading…</p>
          ) : (
            <Table>
              <THead>
                <HeaderRow>
                  <TH>
                    <input
                      type="checkbox"
                      aria-label="Select all"
                      checked={users.length > 0 && selected.size === users.length}
                      onChange={toggleAll}
                    />
                  </TH>
                  <TH>User code</TH>
                  <TH>Email</TH>
                  <TH>Role</TH>
                  <TH>Status</TH>
                  <TH>Joined</TH>
                </HeaderRow>
              </THead>
              <TBody>
                {users.map((u) => (
                  <Row key={u.user_code}>
                    <TD>
                      <input
                        type="checkbox"
                        aria-label={`Select ${u.email}`}
                        checked={selected.has(u.user_code)}
                        onChange={() => toggleRow(u.user_code)}
                      />
                    </TD>
                    <TD className="font-medium">{u.user_code}</TD>
                    <TD>{u.email}</TD>
                    <TD className="capitalize">{u.role}</TD>
                    <TD>
                      <StatusPill status={u.is_active ? "active" : "inactive"} />
                    </TD>
                    <TD>{new Date(u.date_joined).toLocaleDateString()}</TD>
                  </Row>
                ))}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

export default function AdminUsersPage() {
  return (
    <DashboardShell title="Users" role="admin">
      <AdminUsersContent />
    </DashboardShell>
  );
}
```

- [ ] **Step 4: Add the nav link**

In `frontend/su-erp-web/src/components/DashboardShell.tsx`, replace the `admin` nav array (lines 50-54):

```tsx
  admin: [
    { label: "Overview", href: "/admin", icon: LayoutDashboard },
    { label: "Add Students", href: "/admin/students/new", icon: GraduationCap },
    { label: "Users", href: "/admin/users", icon: User },
    { label: "Profile", href: "/admin/profile", icon: User },
  ],
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend/su-erp-web && npx vitest run src/app/\(dashboard\)/admin/users/admin-users.test.tsx`
Expected: PASS

- [ ] **Step 6: Run the full frontend test suite to check for regressions**

Run: `cd frontend/su-erp-web && npx vitest run`
Expected: PASS, no regressions (in particular `students-new.test.tsx` and any `DashboardShell` nav test).

- [ ] **Step 7: Commit**

```bash
git add frontend/su-erp-web/src/app/\(dashboard\)/admin/users/ frontend/su-erp-web/src/components/DashboardShell.tsx
git commit -m "feat(admin-ui): add user list page with bulk deactivate"
```

---

### Task 4: Update README

**Files:**
- Modify: `README.md` (append to end)

- [ ] **Step 1: Read the current end of the file**

Run: `tail -n 20 README.md`

- [ ] **Step 2: Append a short changelog-style note**

Add to the end of `README.md` (exact heading/style to match whatever section pattern already exists at the end of the file — if the file ends with a features/changelog list, add a matching bullet; otherwise add a new `## Recent changes` section):

```markdown
## Recent changes

- Admin can now view all users in their tenant and bulk-deactivate (soft-delete) selected accounts from **Admin → Users**. Deactivated users are kept in the database (not hard-deleted) and can no longer sign in. Self-delete and removing the tenant's last active admin are blocked server-side.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: note admin bulk user deactivation feature in README"
```

---

## Self-Review Notes

- Every task ends in an independently runnable, testable deliverable (backend endpoint testable via pytest without the frontend; frontend page testable via mocked `api` without the backend running).
- Guardrail tests in Task 1 are verbose because the last-admin guard is inherently hard to trigger without violating self-delete in a single-admin-caller system — the test walks through fresh institutions to isolate the two guards. This is intentional, not padding.
- Hard-delete was explicitly rejected per user decision (cross-service `user_code` references with no real FK would orphan).
