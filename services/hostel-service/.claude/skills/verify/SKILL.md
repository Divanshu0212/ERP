---
name: verify (hostel-service)
description: Recipe for verifying hostel-service changes end-to-end against the live docker-compose stack (gateway on :8080).
---

# Verifying hostel-service against the live stack

Stack must already be up: `docker compose -f infra/docker-compose.yml up -d`
(gateway at http://localhost:8080).

## Getting a real, working JWT

Hand-minting a JWT with pyjwt (see `hostel/tests/test_allocate.py::_make_token`,
signing key `JWT_SIGNING_KEY=dev-insecure-shared-jwt-key` from
`infra/docker-compose.yml`) works fine for endpoints hostel-service checks
purely by JWT claims (role/tenant/sub).

**It does NOT work** for any hostel-service endpoint that calls
`hostel/lookups.py:resolve_user_by_email` (e.g. `POST /blocks`'s
`warden_email`, or any row in `allocate/bulk` with a real email) — that
function calls through the gateway to auth-service's
`GET /api/v1/auth/users/by-email/`, which does a real tenant-scoped DB
lookup. A fabricated tenant/user UUID will 404 there even though the JWT
signature itself verifies fine.

So for anything touching email resolution, provision a **real** tenant + user
via auth-service and log in for a genuine token:

```bash
# 1. Create a fresh institution + admin (idempotent-ish; reuses by slug)
docker exec auth-service python manage.py create_institution \
  --slug verify-test-$(date +%s) --name "Verify Test Univ" \
  --admin-email verify-admin@test.edu --admin-password 'Passw0rd!123'
# prints institution_id=... admin_id=...

# 2. Get the slug if needed (create_institution only prints it if newly created)
docker exec auth-service python manage.py shell -c "
from accounts.models import Institution
print(Institution.objects.get(id='<institution_id>').slug)
"

# 3. Real login through the gateway -> real signed JWT
curl -s -X POST http://localhost:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"institution_slug":"<slug>","email":"verify-admin@test.edu","password":"Passw0rd!123"}'
# -> data.access is a real JWT, role=admin, tenant=<institution_id>
```

Admin role satisfies every hostel-service `role_required("warden", "admin")`
check, so one admin login covers all warden-only endpoints too.

To probe role enforcement (403 cases), create a second user with
`role=User.Role.STUDENT` via `User.objects.get_or_create(...)` in the same
shell and log in separately.

## Seeding a Block + Room (needed before allocate/available-rooms tests)

```bash
TOKEN=<access token>

curl -s -X POST http://localhost:8080/api/v1/hostel/blocks \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Block A","gender_type":"M","warden_email":"verify-admin@test.edu"}'
# warden_email MUST be a real user in the same tenant (see above)

curl -s -X POST http://localhost:8080/api/v1/hostel/rooms \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"block_id":"<block_id>","room_no":"101","capacity":2}'
```

## Exercising the CSV template + bulk import round trip

```bash
# Download the pre-filled available-rooms CSV (warden/admin only)
curl -s -D - http://localhost:8080/api/v1/hostel/rooms/available-template \
  -H "Authorization: Bearer $TOKEN" -o template.csv
# Content-Type: text/csv; Content-Disposition: attachment; filename="allocation-template.csv"

# Upload it back as-is (blank student_email -> row gets skipped, not failed)
curl -s -X POST http://localhost:8080/api/v1/hostel/allocate/bulk \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@template.csv;type=text/csv;filename=allocation-template.csv"
# -> {"total_rows":1,"success_count":0,"fail_count":0,"skipped_count":1}

curl -s http://localhost:8080/api/v1/hostel/allocations/import-logs \
  -H "Authorization: Bearer $TOKEN"
# skipped_count shows on the list; row-level detail is at
# GET /api/v1/hostel/allocations/import-logs/<batch_id>
```

Fill in a real `student_email` in a CSV row (matching a real user in-tenant)
to exercise the `success` path in the same batch, and use an email you know
doesn't exist to exercise `failed` — all three statuses (`success`,
`skipped`, `failed`) can be produced in one multi-row upload to check the
counters don't cross-contaminate.
