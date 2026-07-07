# user_code identity migration + universal profile system

Status: approved for planning
Scope: auth-service, student-service, hostel-service, finance-service, canteen-service,
transport-service, grievance-service, notification-service, attendance-service, shared
event schemas, gateway (none), frontend.

## Problem

Every user is identified by UUID internally and by email at the login/lookup edges
(`UserByEmailView`, hostel-service's `resolve_user_by_email`). There is no per-user
profile data anywhere (roll number beyond students, address, phone, DOB, etc.) and no
frontend profile tab for any role. Non-student roles (warden, driver, admin,
canteen_owner, faculty, alumni) have no profile model at all.

Goal: every user (except superadmin) gets a unique, admin-assigned `user_code` that
becomes their actual database primary key and the value used in every cross-service
reference, in the JWT, in URLs, and in the UI — replacing UUID and replacing email as
the "how do I find this user" mechanism everywhere except the login form itself.

## Decisions (locked)

1. **Literal PK swap.** `User.id` (currently UUID) is replaced by `user_code` as the
   real primary key. Every service's stored UUID reference to a user is retyped to
   hold `user_code` instead. This is a full-system migration, not an additive lookup
   field.
2. **Field name: `user_code`**, uniform across every role and every service. No
   role-conditional naming (not `roll_no` for students only).
3. **Format:** alphanumeric + hyphen/underscore, max 30 chars. Admin enters it
   manually at user-creation time (no auto-generation). Unique per tenant (same
   uniqueness scope as email today: `UniqueConstraint(fields=["tenant", "user_code"])`).
4. **Login stays email + password + institution_slug.** `user_code` is not a login
   credential — it's the internal/display/lookup identifier everywhere else
   (URLs, cross-service FKs, JWT `sub`, admin search, profile display).
5. **Superadmin fully excluded.** Superadmin keeps UUID `id`, email login, no
   `user_code`, no `UserProfile` row, no profile tab. Platform-bootstrap account only.
6. **Profile data home: new `UserProfile` model in auth-service**, 1:1 with `User`
   (pk = `user_code` FK), same DB. Fields: `phone`, `address`, `date_of_birth`,
   `gender`, `emergency_contact_name`, `emergency_contact_phone`, `blood_group`,
   `profile_photo_url`. All optional/blank — filled in later via the profile tab, not
   required at creation time.
7. **No new role-specific profile tables** (no `WardenProfile`, `DriverProfile`, etc.)
   for this pass. `StudentProfile` (department/batch/semester/cgpa) stays as-is in
   student-service, just re-keyed from `user_id: UUIDField` to `user_code: CharField`.
8. **Greenfield.** No data migration/backfill. `docker compose down -v && up` rebuilds
   all 13 databases from new migrations. No production data exists to preserve.
9. **Rename FK fields to `user_code` everywhere**, even though today's names vary
   (`user_id`, `student_id`, `warden_id`, `driver_id`, `raised_by`, `assigned_to`,
   `comment_by`, `decided_by`, `uploaded_by`). Rationale: a field literally named
   `student_id` holding a `user_code` string is misleading. Every one of these becomes
   a `CharField(max_length=30)` named consistently — see field rename table below.

   Exception: fields whose name describes a *role relationship*, not just "this is a
   user reference" (`warden_id`, `driver_id`, `raised_by`, `assigned_to`,
   `comment_by`, `decided_by`, `uploaded_by`) keep their existing name — only the
   **type** changes from `UUIDField` to `CharField(max_length=30)`. Renaming
   `warden_id` to `warden_user_code` everywhere would bloat every call site for no
   readability gain; the surrounding code already makes clear it's a user_code.
   Only the generic `user_id` / `student_id` names (which say nothing about role)
   get renamed to `user_code` / `student_user_code` respectively, since those are the
   ones that actively read as "this is still a UUID."

   Concretely:
   - `user_id` → `user_code` (student-service.StudentProfile, notification-service.Notification)
   - `student_id` → `student_user_code` (hostel Allocation/LeaveRequest/RoomRequest/Complaint,
     finance Invoice, canteen Order, transport Booking/Pass, attendance AttendanceRecord)
   - `warden_id`, `driver_id`, `raised_by`, `assigned_to`, `comment_by`, `decided_by`,
     `uploaded_by` → unchanged name, type only changes to `CharField(max_length=30)`

10. **JWT `sub` claim** changes from UUID string to `user_code` string. Everything
    reading `request.user.id` / `claims["sub"]` keeps working unchanged (it's already
    treated as an opaque string in every business service — `SimpleUser` never
    assumed UUID shape).
11. **Event schemas** (`shared/event-schemas/*.json`): every `user_id`/`student_id`/
    `raised_by` payload field's `format: uuid` constraint is dropped (becomes a plain
    string with `maxLength: 30`). Event *names* and envelope shape are unchanged —
    this is a payload field type change, not a schema version bump.
12. **Email lookup retirement:** `UserByEmailView` and `resolve_user_by_email` (hostel
    lookups.py) are replaced by an equivalent resolve-by-user_code path — but since
    admins/wardens create allocations/blocks by referencing a person, and user_code is
    now the primary human-enterable identifier, the frontend forms that today collect
    `student_email`/`warden_email` switch to collecting `student_user_code`/
    `warden_user_code` directly, and the resolve endpoint becomes
    `GET /api/v1/auth/users/by-code/?user_code=...` (still needed for cross-service
    "does this user_code exist in my tenant" validation, just keyed differently).
    Email remains on `User` purely as a contact/login field — no service ever
    resolves *by* it again except the login view itself.

## Data model changes

### auth-service (`accounts/models.py`)

```python
class User(AbstractBaseUser, PermissionsMixin):
    user_code = models.CharField(max_length=30, primary_key=True)  # was: id UUIDField pk
    tenant = models.ForeignKey(Institution, ...)
    email = models.EmailField()
    role = models.CharField(...)
    ...
    USERNAME_FIELD = "email"          # unchanged — login is still email-based
    REQUIRED_FIELDS = ["tenant", "role", "user_code"]

    class Meta:
        constraints = [
            UniqueConstraint(fields=["tenant", "email"], name="unique_email_per_tenant"),
            UniqueConstraint(fields=["tenant", "user_code"], name="unique_user_code_per_tenant"),
        ]
```

Superadmin: created via `bootstrap_superadmin` management command, keeps `user_code`
null/unused — simplest correct approach is superadmin stays on a **separate code path**:
`User.user_code` is nullable, populated for every role except `superadmin`, with a
partial unique constraint (`UniqueConstraint(..., condition=~Q(role="superadmin"))`)
so multiple superadmins (across institutions, if that ever happens) never collide on
a shared null.

New model:

```python
class UserProfile(models.Model):
    user = models.OneToOneField(User, primary_key=True, on_delete=models.CASCADE, related_name="profile")
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, blank=True)
    emergency_contact_name = models.CharField(max_length=255, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True)
    blood_group = models.CharField(max_length=5, blank=True)
    profile_photo_url = models.URLField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
```

Not created for superadmin. Created lazily (get-or-create) on first profile fetch/edit
for every other role, or eagerly at user-creation time as an empty row — eager is
simpler (one less get-or-create branch in the profile view).

### student-service (`students/models.py`)

`StudentProfile.user_id: UUIDField` → `StudentProfile.user_code: CharField(max_length=30)`.
`StudentProfile.roll_no` is dropped — per decision 2, there is one roll-number concept
platform-wide (`user_code`), not a separate per-student `roll_no`. The `user_code` FK
value carried on `StudentProfile` *is* the student's roll number; `roll_no` becomes
redundant and is removed from the model and its serializer's field list.

### Every dependent service

Retype the FK field per the rename table in decision 9. All become
`CharField(max_length=30)`, no `db_index=True` change needed (already indexed via
existing model Meta where present, add where missing).

## API changes

- `auth-service`: `UserByEmailView` is removed. Add `UserByCodeView`
  (`GET /api/v1/auth/users/by-code/?user_code=`) as its direct replacement — same
  `role_required("warden", "admin")` permission, same response shape
  (`user_code`, `email`, `role`, `tenant`) as today's `UserByEmailSerializer` plus
  `user_code`. This is the only resolve-a-user endpoint post-migration; email is no
  longer a valid lookup key anywhere.
- `auth-service`: new `GET/PATCH /api/v1/auth/users/me/profile/` — fetch/update the
  calling user's own `UserProfile`. 403 for superadmin (no profile exists).
- `auth-service`: admin-facing `GET /api/v1/auth/users/{user_code}/profile/` for
  admin/warden to view (not edit) another user's profile where role permits
  (e.g. warden viewing a student's emergency contact).
- User-creation endpoints (register, admin-create-user, superadmin-create-admin) gain
  a required `user_code` input field, validated unique-per-tenant, format-checked
  (alphanumeric/hyphen/underscore, ≤30 chars).
- `hostel-service`: `AllocateRequestSerializer.student_email` → `student_user_code`;
  `BlockCreateSerializer.warden_email` → `warden_user_code`. `resolve_user_by_email`
  → `resolve_user_by_code`, hitting the new `by-code` endpoint.

## Frontend changes

- **Profile tab**, one per role, added to every dashboard shell (`admin`, `warden`,
  `faculty`, `driver`, `student`, `canteen`/`canteen-owner`) — NOT superadmin. Shows
  `user_code`, email (read-only), role, tenant, plus editable common fields (phone,
  address, DOB, gender, emergency contact, blood group, photo URL). One shared
  `ProfilePage`/`ProfileForm` component parametrized by role, not 6 separate
  implementations.
- Login form: unchanged (institution slug, email, password).
- `DashboardShell.tsx:107` bug fix: `userEmail` variable currently holds JWT `sub`
  (was UUID, will be `user_code`) but is fed to `Avatar`'s `initialsFromEmail`, which
  expects an `@`-containing email. Fix: fetch the user's actual email (and optionally
  `profile_photo_url`) via the new `/auth/users/me/profile/`-adjacent `me` endpoint
  (or existing `/auth/users/me/` if present) instead of misusing `sub`. Avatar shows
  photo if `profile_photo_url` is set, else initials from real email.
- Admin console forms (block creation, allocation creation, bulk import) that
  currently collect `student_email`/`warden_email`: relabel inputs to
  `student_user_code`/`warden_user_code`. Bulk import CSV/XLSX column renamed from
  `student_email` to `student_user_code`.
- User-creation forms (admin creating student/faculty/etc, superadmin creating
  institution admin) gain a required "User Code / Roll Number" input.

## Migration mechanics

Greenfield — no backfill. Order of work:
1. auth-service: `User.user_code` pk swap + `UserProfile` model + migrations +
   updated serializers/views (register, admin-create-user, superadmin-create-admin,
   `by-code` endpoint, `me/profile` endpoints) + JWT issuance (`sub` = `user_code`).
2. shared/libs/suerp_common: no change needed (auth.py already treats `sub` as an
   opaque string — verified in exploration, `SimpleUser` does no UUID parsing).
3. shared/event-schemas/*.json: drop `format: uuid`, add `maxLength: 30` on the
   affected payload fields.
4. Each dependent service (student, hostel, finance, canteen, transport, grievance,
   notification, attendance): retype FK fields per rename table, update
   serializers/views that reference old field names, update event payload
   construction/consumption call sites (inventory in exploration above — ~25 view
   call sites, ~10 publish/consume call sites).
5. Frontend: profile tab + component, form relabeling, `DashboardShell` avatar fix.
6. `docker compose down -v && up --build -d` to rebuild all databases from new
   migrations.

## Testing

- auth-service: user_code uniqueness-per-tenant, format validation, superadmin
  exclusion (no user_code, no profile), profile CRUD, JWT sub carries user_code.
- Each dependent service: existing tests referencing `user_id`/`student_id` fixtures
  updated to use user_code-shaped strings instead of `uuid4()`; ownership-check tests
  (finance receipt download, transport driver-schedule, grievance ticket visibility)
  re-verified since they do string comparison on the renamed field — logic unchanged,
  only fixture data shape changes.
- Frontend: profile tab render/submit per role, avatar fix, relabeled forms
  (student_user_code/warden_user_code) submit correctly, bulk import CSV header
  change reflected in test fixtures.
- Full-chain integration test (mirroring the existing hostel→finance→notification
  saga test) re-run to confirm event payloads carrying user_code (not UUID) still
  flow correctly end-to-end.

## Out of scope (explicitly deferred)

- Role-specific profile tables beyond `StudentProfile` (no `WardenProfile` etc.).
- Auto-generation of `user_code` values — always admin-entered.
- Changing login credential from email to user_code.
- Superadmin gaining user_code/profile.
- Data migration/backfill scripts (greenfield reset only).
