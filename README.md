# SU-ERP — Multi-Tenant University ERP

A multi-tenant SaaS ERP for universities: a microservice, event-driven, ML-assisted
platform that runs many institutions on shared infrastructure and scales to thousands
of concurrent users. Each institution ("tenant") shares the same databases and schemas;
rows are isolated by a `tenant_id` column enforced in the ORM layer.

Built for two audiences: **institution staff** (finance, wardens, transport, exams,
placements, admins) who operate the university, and **students** who allocate hostel
rooms, pay fees, raise grievances, and track their records — all through one web app.

---

## Table of contents

- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Service inventory](#service-inventory)
- [Running the stack locally](#running-the-stack-locally)
- [Running the tests](#running-the-tests)
- [Demo 1 — the hostel saga](#demo-1--the-hostel-saga-hostel--finance--notification)
- [Demo 2 — the ML grievance escalation](#demo-2--the-ml-grievance-escalation-grievance--ai--notification)
- [Screenshots](#screenshots)
- [Correctness under adversarial conditions](#correctness-under-adversarial-conditions)
- [Multi-tenancy](#multi-tenancy)
- [Zero-trust identity](#zero-trust-identity)
- [Event model](#event-model)
- [Observability & CI](#observability--ci)

---

## Architecture

```
                         ┌──────────────────────────────┐
   Browser ─────────────▶│  Frontend (Next.js App Router)│
                         │  frontend/su-erp-web           │
                         └───────────────┬────────────────┘
                                         │  only talks to the gateway
                                         │  /api/v1/*   (JWT bearer)
                                         ▼
                         ┌──────────────────────────────┐
                         │  API Gateway (Nginx :8080)    │
                         │  path routing · rate limiting  │
                         └───────────────┬────────────────┘
        ┌────────────────────────────────┼───────────────────────────────┐
        ▼                                ▼                                ▼
 ┌────────────┐   ┌────────────┐   ┌────────────┐   ...   ┌────────────┐
 │ auth (:8000)│  │ finance    │  │ hostel      │         │ ai (:8001) │
 │ Django+DRF  │  │ Django+DRF │  │ Django+DRF  │         │  FastAPI   │
 └──────┬─────┘   └─────┬──────┘   └─────┬──────┘         └─────┬──────┘
        │  (every service verifies the JWT itself — zero-trust)  │
        └──────────────┬─────────────────┬─────────────────────┘
                       │ publish/consume  │
                       ▼                  ▼
        ┌─────────────────────────────────────────────┐
        │  RabbitMQ — topic exchange "suerp.events"    │
        │  routing key = event type                     │
        │  transactional outbox → drained by celery-beat│
        │  idempotent inbox consumers (dedupe by id)    │
        └─────────────────────────────────────────────┘
                       │
   ┌───────────────────┼───────────────────────────────────────────┐
   ▼                   ▼                  ▼                ▼          ▼
┌────────┐      ┌────────────┐     ┌────────┐      ┌───────────┐ ┌────────┐
│Postgres│◀────▶│  PgBouncer │     │ Redis  │      │Prometheus │ │Grafana │
│  16    │      │ (txn pool) │     │cache/  │      │  scrape   │ │dashbds │
│13 DBs  │      │  :6432     │     │ celery │      └───────────┘ └────────┘
└────────┘      └────────────┘     └────────┘
```

The frontend never talks to a service directly — it calls the Nginx gateway, which
routes `/api/v1/*` to the owning service and applies IP rate limiting. Services
communicate with each other only through events on the RabbitMQ bus, never by
synchronous cross-service calls.

---

## Tech stack

| Layer            | Technology                                                        |
| ---------------- | ----------------------------------------------------------------- |
| Frontend         | Next.js (App Router) + Tailwind CSS                               |
| API gateway      | Nginx (path routing, per-IP rate limiting), listens `:8080`      |
| Business services| Django 5 + Django REST Framework                                 |
| AI service       | FastAPI + VADER sentiment + keyword-rule urgency                 |
| Auth             | JWT (HS256), shared signing key, zero-trust per-service verify   |
| Event bus        | RabbitMQ topic exchange `suerp.events` (routing key = event type)|
| Reliability      | Transactional outbox + idempotent inbox consumers                |
| Database         | PostgreSQL 16, one DB per service (13 DBs)                        |
| Connection pool  | PgBouncer (transaction pooling) `:6432`                          |
| Cache / broker   | Redis (cache + Celery broker/result)                             |
| Async workers    | Celery + celery-beat (outbox drain, timeouts)                    |
| Shared lib       | `suerp_common` (tenant model, outbox, inbox, events, envelopes)  |
| Observability    | Prometheus + Grafana (`/metrics` per service)                    |
| CI               | GitHub Actions (lint → pytest+cov → security → docker build)     |

---

## Service inventory

All Django services listen internally on `:8000`; ai-service on `:8001`. Everything is
reached through the gateway on `:8080` at `/api/v1/...`.

| Service              | Purpose                                         | Gateway prefix           | Kind    | Status |
| -------------------- | ----------------------------------------------- | ------------------------ | ------- | ------ |
| auth-service         | Register/login, JWT issuance, users             | `/api/v1/auth/`          | Django  | full   |
| finance-service      | Invoices & payments; saga billing               | `/api/v1/finance/`       | Django  | full   |
| hostel-service       | Rooms & allocations; saga orchestration         | `/api/v1/hostel/`        | Django  | full   |
| transport-service    | Routes & transport records                      | `/api/v1/transport/`     | Django  | full   |
| grievance-service    | Ticketing + ML-driven auto-escalation           | `/api/v1/grievance/`     | Django  | full   |
| notification-service | Student inbox; consumes domain events           | `/api/v1/notify/`        | Django  | full   |
| ai-service           | Sentiment/urgency scoring, chatbot intent       | `/api/v1/ai/`            | FastAPI | full   |
| canteen-service      | Menu, orders & Razorpay checkout                | `/api/v1/menu-items/`, `/api/v1/orders/` | Django | full |
| student-service      | Student master records                          | `/api/v1/students/`      | Django  | stub   |
| attendance-service   | Attendance tracking                             | `/api/v1/attendance/`    | Django  | stub   |
| exam-service         | Exams & results                                 | `/api/v1/exams/`         | Django  | stub   |
| library-service      | Books & lending                                 | `/api/v1/books/`         | Django  | stub   |
| placement-service    | Placement drives                                | `/api/v1/placements/`    | Django  | stub   |
| analytics-service    | Cross-service metrics                           | `/api/v1/metrics/`       | Django  | stub   |

"stub" services expose working CRUD prototypes on the tenant/JWT/event foundation;
the eight "full" services carry the complete business logic and the two demo flows.

---

## Running the stack locally

**Prerequisites:** Docker + Docker Compose, and (for tests) Python 3.12 with a `.venv`.

1. Copy the env templates. Each service ships a `.env.example`; the defaults already
   point at the local Docker hostnames (`pgbouncer`, `redis`, `rabbitmq`), so for a
   plain local run you can use them as-is:

   ```sh
   for f in services/*/.env.example; do cp "$f" "$(dirname "$f")/.env"; done
   ```

2. Bring up the whole stack (infra + gateway) with the Makefile:

   ```sh
   make up      # docker compose -f infra/docker-compose.yml up --build
   ```

   This starts PostgreSQL 16 (with all 13 service DBs created by `init-multi-db.sh`),
   PgBouncer, Redis, RabbitMQ, Prometheus, Grafana, and the Nginx gateway on `:8080`.

3. Frontend (separate dev server):

   ```sh
   cd frontend/su-erp-web
   npm install
   npm run dev        # Next.js on http://localhost:3000
   ```

Tear everything down (including volumes):

```sh
make down          # docker compose ... down -v
```

### Key environment variables

| Variable            | Meaning                                                            |
| ------------------- | ----------------------------------------------------------------- |
| `SECRET_KEY`        | Django secret (per service; dev default provided)                |
| `DEBUG`             | Django debug flag (`1` in dev)                                    |
| `JWT_SIGNING_KEY`   | **Shared** HS256 key — the same value in every service            |
| `DATABASE_URL`      | `postgres://suerp:suerp@pgbouncer:6432/<service-db>`             |
| `READ_DATABASE_URL` | Optional read-replica alias; defaults to `DATABASE_URL`          |
| `REDIS_URL`         | Cache + Celery broker/result                                     |
| `RABBITMQ_URL`      | Event bus (`amqp://guest:guest@rabbitmq:5672/`)                  |
| `GATEWAY_URL`       | ai-service only — base URL it uses to call owning services        |

---

## Running the tests

**Backend** (~143+ tests across the shared lib and all services):

```sh
make test                                   # pytest over shared/ and services/
# or a single service:
.venv/bin/pytest services/finance-service
```

**Lint / format:**

```sh
make lint      # ruff + black --check + isort --check
make fmt       # auto-fix
```

**Frontend** (19 tests, Vitest):

```sh
cd frontend/su-erp-web
npm test       # vitest run
```

---

## Demo 1 — the hostel saga (hostel ↔ finance ↔ notification)

A distributed saga that allocates a hostel seat, bills for it, and only confirms the
seat once payment succeeds. Correlation is **order-independent** (the payment event and
the invoice event may arrive in either order), and the timeout compensation **never
releases a seat that has already been paid for**.

**Flow of events:**

```
student allocates room
  hostel → hostel.allocation.requested
              finance consumes → creates invoice
  finance → finance.invoice.created
student pays the invoice
  finance → finance.payment.success
              hostel correlates by invoice_id → confirms seat
  hostel → hostel.allocation.confirmed
              notification writes the student's inbox message
```

If payment fails or times out, finance emits `finance.payment.failed` and hostel runs
the compensating action, emitting `hostel.allocation.released` (freeing the seat).

**Step by step (through the gateway on `:8080`):**

1. **Register** a student:
   ```sh
   curl -sX POST localhost:8080/api/v1/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"email":"stu@uni.edu","password":"Passw0rd!","role":"student"}'
   ```
2. **Login** to get a JWT:
   ```sh
   TOKEN=$(curl -sX POST localhost:8080/api/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email":"stu@uni.edu","password":"Passw0rd!"}' | jq -r .data.access)
   ```
3. **Allocate** a room (emits `hostel.allocation.requested`):
   ```sh
   curl -sX POST localhost:8080/api/v1/hostel/allocations \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"room_id":"<ROOM_UUID>","student_id":"<STUDENT_UUID>"}'
   ```
   Finance consumes it and raises an invoice (`finance.invoice.created`).
4. **Pay** the invoice (emits `finance.payment.success`):
   ```sh
   curl -sX POST localhost:8080/api/v1/finance/invoices/<INVOICE_UUID>/pay \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"idempotency_key":"pay-1"}'
   ```
5. **Watch the confirmation.** hostel correlates the payment to the allocation and
   emits `hostel.allocation.confirmed`; notification-service writes the student inbox
   entry. Verify:
   ```sh
   curl -s localhost:8080/api/v1/hostel/allocations/<ALLOCATION_UUID> \
     -H "Authorization: Bearer $TOKEN"        # status == CONFIRMED
   curl -s localhost:8080/api/v1/notify/ -H "Authorization: Bearer $TOKEN"
   ```

You can inspect the events flowing through the bus in the RabbitMQ management UI
(`http://localhost:15672`, guest/guest).

---

## Demo 2 — the ML grievance escalation (grievance ↔ ai ↔ notification)

A grievance is scored by the AI service; high/critical tickets auto-escalate to a
warden and the student is notified.

**Flow of events:**

```
student raises grievance
  grievance → grievance.created   (payload carries the free text + raised_by)
                ai-service scores it (VADER sentiment + keyword urgency rules)
  ai        → grievance.scored    (sentiment: float, urgency: low|medium|critical)
                grievance auto-escalates high/critical tickets to the warden
                notification messages the student (recipient echoed via raised_by)
```

**Step by step:**

1. Register + login a student (steps 1–2 of Demo 1).
2. **Raise an urgent grievance** (emits `grievance.created`):
   ```sh
   curl -sX POST localhost:8080/api/v1/grievance \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"category":"safety","description":"There was a fire and a gas leak in the hostel, this is an emergency"}'
   ```
   Safety/abuse keywords ("fire", "gas leak", "emergency") drive the urgency to
   `critical`.
3. **Watch it get scored + escalated.** ai-service emits `grievance.scored`;
   grievance-service escalates the ticket. Verify:
   ```sh
   curl -s localhost:8080/api/v1/grievance/<TICKET_UUID> \
     -H "Authorization: Bearer $TOKEN"     # status escalated; urgency=critical
   curl -s localhost:8080/api/v1/notify/ -H "Authorization: Bearer $TOKEN"
   ```

You can also hit the scorer directly:

```sh
curl -sX POST localhost:8080/api/v1/ai/sentiment \
  -H 'Content-Type: application/json' \
  -d '{"text":"the water has been off for three days"}'
# → {"sentiment": <float -1..1>, "urgency": "medium"}
```

---

## Screenshots

Captured live (light mode) against a seeded institution — **NITJ** (`nitj`,
`admin@nitj.in`), provisioned end-to-end through the superadmin console with Indian-named
staff and students, real hostel blocks/rooms, fee structures, room requests, approvals,
payments, and a verified receipt.

### Sign in

![Login](docs/screenshots/login.png)

Tenant-scoped sign-in: institution slug + email + password. The slug selects the tenant;
every downstream request is isolated to it by the JWT `tenant` claim.

### Superadmin — institution provisioning

![Superadmin console](docs/screenshots/superadmin-dashboard.png)

Cross-tenant, platform-scoped: creates institutions and their first admin. Both seeded
tenants (NITJ, PDPM IIITDMJ) shown in the list, provisioned by this exact flow.

### Admin — users, fee structures, hostel setup

![Admin dashboard](docs/screenshots/admin-dashboard.png)

Live tenant counters (users, invoices, allocations, tickets), the invoice and
fee-structure CRUD forms, the full user roster (admin, warden, faculty, driver, canteen
owner, students), hostel blocks (Aryabhatta, Ramanujan, Kalpana Chawla) and their rooms.

![Admin users](docs/screenshots/admin-users.png)

Every user in the tenant with an "include inactive" filter and multi-select **bulk
deactivate** (soft-delete). Self-delete and removing the last active admin are blocked
server-side.

![Admin add students](docs/screenshots/admin-add-students.png)

Single-add form plus CSV bulk-create for onboarding students in one shot.

### Warden — allocation, bulk import, approvals

![Warden dashboard](docs/screenshots/warden-dashboard.png)

One console for the warden's whole workflow: create a single allocation (optionally with a
fee structure + due date), **bulk allocate from CSV/XLSX** with a downloadable
available-rooms template, **import logs** (note the rows correctly logged as *skipped*
rather than failed), the pending room-request approval queue, live pending/confirmed
allocations feeding in from the saga, and escalated grievances.

### Student — request, pay, download receipt

![Student dashboard](docs/screenshots/student-dashboard.png)

Fees & invoices (pending with a **Pay** action, paid with **Download receipt**), room
request submitted and **approved** (Ramanujan-101), real saga/grievance notifications, and
the grievance entry point.

![Student — pay & confirm](docs/screenshots/student-saga-demo.png)

The hostel saga walkthrough: allocate → invoice → pay → confirm, order-independent.

![Student — raise grievance](docs/screenshots/student-escalation-demo.png)

The ML escalation walkthrough: a grievance scored by the AI service, high/critical tickets
auto-escalated to the warden.

### Receipt verification

![Receipt verification](docs/screenshots/verify-receipt.png)

The QR on a downloaded PDF receipt links here — warden/admin-only, HMAC-verified,
tamper-evident. Shown mid-flow: a real NITJ receipt (`RCPT-D16CF940CC3F`, hostel, ₹5000)
scanned and confirmed **valid**.

### Canteen owner — menu & orders

![Canteen owner dashboard](docs/screenshots/canteen-owner-dashboard.png)

A fully-built service: menu-item CRUD (edit price, mark unavailable, delete), an add-item
form, and a live orders queue with a legal status machine (a real order — Masala Dosa ×2,
Chai ×1, ₹135, *Placed* — advanceable to *preparing* or *cancelled*). Students order and
pay through the same Razorpay checkout as fees.

### Other roles

| Faculty | Driver |
| --- | --- |
| ![Faculty](docs/screenshots/faculty-dashboard.png) | ![Driver](docs/screenshots/driver-dashboard.png) |

Faculty/exam and attendance endpoints 404 here — those are prototype/stub services (see
[`docs/REMAINING_MODULES.md`](docs/REMAINING_MODULES.md) for what's fully built vs. stubbed).

### Monitoring under load

![Grafana — SU-ERP Services Overview](docs/screenshots/grafana-dashboard.png)

The Grafana dashboard (`infra/grafana/dashboards/suerp-services.json`) during a real
multi-tenant load run: **2,889 requests at ~9.8 req/s** driven from a client against the
gateway across two tenants (NITJ + a freshly provisioned **IIT Ropar**), with
**p50 10 ms / p95 34 ms** and **zero 5xx**. The dip in the middle is the services being
rebuilt and restarted mid-run; traffic resumes cleanly after.

The 4xx line is real signal, not noise: the load driver deliberately requests a
non-existent allocation UUID on a fixed cadence so the error-rate panel has something to
track.

Two things the run surfaced, both the system behaving correctly:

- **The gateway rate limiter works.** A first, unpaced attempt at ~500 req/s from one IP
  was almost entirely rejected with `429` — nginx enforces 10 r/s per client IP
  (burst 20), and 3 r/s on `/auth/login`. The load driver above is paced under that
  ceiling, which is why its 429 count is zero.
- **The auth lockout works.** A deliberate wrong-password worker tripped
  auth-service's 5-failures-in-15-minutes account lockout, which is exactly its job.

Start the monitoring stack alongside the app (it is behind its own compose profile, so it
stays off by default):

```sh
docker compose -f infra/docker-compose.yml --profile observability up -d prometheus grafana
```

Prometheus at `http://localhost:9090` (all 14 targets healthy), Grafana at
`http://localhost:3000` (admin/admin). Note that Grafana publishes `3000`, the same port
as the Next.js dev server — run one at a time locally, or remap one of them.

---

## Correctness under adversarial conditions

Throughput on a laptop proves little. What this system is actually built to survive is
concurrency, redelivery, and infrastructure failure — so those are what it's tested for.
Each claim below maps to something runnable, not a diagram.

### Race safety — 50 threads, one seat

```sh
make test-concurrency
```

`hostel/tests/test_concurrency.py` runs real OS threads against **real PostgreSQL** (not
the SQLite fallback, where `select_for_update()` is a no-op and a green test would prove
nothing — it skips instead of passing vacuously) using `TransactionTestCase`, so every
thread gets its own committed connection:

| Scenario | Guarantee |
| --- | --- |
| 50 students race for the **last** seat | exactly **1** wins, 49 clean `RoomFullError`s, room lands at `2/2` |
| 30 students, 3 free seats | exactly **3** win — never over-allocated |
| 1 student fires 20 concurrent requests | exactly **1** allocation, capacity consumed once |
| Two tenants allocate concurrently | 1 winner each, zero cross-tenant leakage |

The test is load-bearing, not decorative: with `select_for_update()` neutered in-memory,
the last-seat race reproduces the bug — **3 students win the same seat and the room
over-allocates**. That failure is what the lock in `hostel/services.py` prevents.

### Broker outage mid-saga — the outbox earns its keep

```sh
make chaos          # ./scripts/chaos_broker_outage.sh
```

Kills RabbitMQ in the middle of a live allocation saga and asserts recovery:

```
[1] killing RabbitMQ mid-flight
  ✓ RabbitMQ is DOWN
[2] allocating a seat with NO broker (the write must still succeed)
  ✓ HTTP 201 — allocation created with the broker DOWN
  ✓ event is SAFE in the outbox, unpublished: backlog 0 -> 1
[3] bringing RabbitMQ back
  ✓ RabbitMQ is UP and healthy
[4] waiting for the outbox to drain by itself (beat runs every 5s)
  ✓ backlog drained back to 0 — no manual replay, no lost events
[5] confirming the downstream saga step ran
  ✓ finance consumed the recovered event and raised an invoice for 11000.00
```

This is the **dual-write problem**, demonstrated rather than asserted. Publishing inside
the request handler would have dropped that event the moment the broker died, wedging the
saga with a seat reserved and no invoice. Because `publish_event()` only inserts an outbox
row inside `transaction.atomic()`, the state change and the event commit together — a dead
broker can't fail the user's request or lose the event.

### Already covered by the unit suite

The hard distributed-systems cases are tested in `hostel/tests/test_saga.py`:

- **Out-of-order correlation** — `payment.success` arriving *before* `invoice.created`
  still confirms the seat (and the same for the failure/release path).
- **Idempotency** — the same `event_id` redelivered confirms once and emits one event.
- **Timeout compensation never releases a paid seat** — including the paid-but-uncorrelated
  case, which is the subtle one.

---

## Multi-tenancy

Model: **shared-database, shared-schema, row-level `tenant_id`.** Every business row
carries a `tenant_id`. The `suerp_common` shared library provides:

- `TenantModel` — abstract base adding the `tenant_id` column,
- `TenantManager` — a manager whose default queryset is scoped to the current tenant
  (with an `all_objects` escape hatch for consumers/system code),
- `TenantMiddleware` — sets the current tenant from the JWT's `tenant` claim per request.

Because every service reads the tenant from the (self-verified) JWT, one institution
can never read or write another's rows. Cross-tenant isolation is covered by tests in
every model-owning service.

---

## Zero-trust identity

There is no trusted network boundary. Tokens are JWTs signed **HS256** with a
`JWT_SIGNING_KEY` shared across all services. **Every service verifies the signature
itself** and reads `sub` (user id), `role`, and `tenant` from the claims — a service
never trusts a header set by an upstream. The gateway forwards the `Authorization`
bearer unchanged; a spoofed identity header from a client is ignored (covered by a
header-spoofing test in auth).

---

## Event model

- **Exchange:** a single RabbitMQ topic exchange, `suerp.events`; the routing key is the
  event `type` (e.g. `finance.payment.success`). Consumers bind queues to the routing
  keys they care about. Poison messages are dead-lettered (`suerp.events.dlx`).
- **Envelope:** every event is `{ event_id, type, tenant_id, occurred_at, payload }`.
  JSON Schemas for every event type live in [`shared/event-schemas/`](shared/event-schemas/).
- **Transactional outbox:** producers call `suerp_common.outbox.publish_event(type,
  tenant_id, payload)` **inside** `transaction.atomic()`. This only inserts an outbox
  row — it never touches the broker — so the state change and the event commit or roll
  back together. A celery-beat task drains outbox rows to RabbitMQ.
- **Idempotent inbox:** consumers are wrapped with `@idempotent` (from
  `suerp_common.inbox`), which dedupes by `event_id`, so at-least-once redelivery is
  harmless.
- **Response envelope (HTTP):** every API returns `{ success, data, message, errors }`.
  Pagination defaults to 20 items, max 100. All routes are under `/api/v1/...`.

### Event catalog

| Event                          | Producer     | Consumers                          |
| ------------------------------ | ------------ | ---------------------------------- |
| `user.registered`              | auth         | (downstream provisioning)          |
| `hostel.allocation.requested`  | hostel       | finance                            |
| `finance.invoice.created`      | finance      | hostel                             |
| `finance.payment.success`      | finance      | hostel                             |
| `finance.payment.failed`       | finance      | hostel                             |
| `hostel.allocation.confirmed`  | hostel       | notification                       |
| `hostel.allocation.released`   | hostel       | notification (compensation)        |
| `grievance.created`            | grievance    | ai                                 |
| `grievance.scored`             | ai           | grievance, notification            |
| `hostel.swap.requested`        | hostel       | notification                       |

---

## Planned: hostel allocation workflow v2

Design notes for three in-progress hostel-service/finance-service features (student
room requests, fee-configurable receipts, room swaps). Not yet implemented — this is
the agreed design, kept here instead of a separate spec doc.

### 1. Room-aware bulk allocation template

- `GET /api/v1/hostel/rooms/available-template` (new) returns a CSV of currently
  available rooms only: `room_id,room_name,student_email` (email column blank).
  `room_name` is `"{block.name} - {room.room_no}"`. Replaces the static
  `public/sample-allocation-import.csv` link on the warden dashboard.
- `AllocateBulkView`/`_parse_rows`: a row with a blank `student_email` no longer counts
  as a failure. New `AllocationImportRow.Status.SKIPPED` — logged with reason "no email
  provided", excluded from `fail_count` (only real errors count as failed).

### 2. Student room requests + warden approval + configurable fees + receipts

- New `RoomRequest` model (hostel-service): `student_id`, `room` (FK), `status`
  (pending/approved/rejected), `requested_on`, `decided_on`, `decided_by`,
  `rejection_reason`.
- Student: browses available rooms, `POST /api/v1/hostel/room-requests` to request one.
- Warden: `GET /api/v1/hostel/room-requests?status=pending`,
  `POST .../{id}/approve` (choosing a `FeeStructure`) or `.../{id}/reject` (with reason).
  Approve calls the existing `create_allocation()` unchanged — the payment saga
  (invoice → pay → confirm) proceeds exactly as today.
- `FeeStructure` (finance-service, model already existed but was unused) gets a real
  CRUD surface for warden/admin, replacing the hardcoded `HOSTEL_FEE_AMOUNT` constant
  in `billing/consumers.py`. Invoice amount/purpose come from the chosen fee structure.
- On `finance.payment.success`, a new consumer handler populates the existing (until
  now unused) `Receipt` model: generates a PDF (via `reportlab`) with university name
  (denormalized onto `Invoice` at creation time, sourced from auth-service's
  `Institution.name`), amount, purpose, and a signed verification token (HMAC using the
  shared `JWT_SIGNING_KEY`) rendered as both a QR code and a plain-text code.
  - `GET /api/v1/finance/receipts/{id}/pdf` — student downloads.
  - `POST /api/v1/finance/receipts/verify` — warden/admin verify a token.

### 3. Room exchange (swap) between students

- New `SwapRequest` model (hostel-service): `initiator_student_id`,
  `initiator_allocation` (FK), `target_room` (FK), `acceptor_student_id` (nullable),
  `acceptor_allocation` (nullable FK), `status`
  (pending_acceptance/accepted/approved/rejected/cancelled), `requested_on`,
  `decided_on`, `decided_by`.
- Student A picks a target room (any occupied room that isn't their own) —
  `POST /api/v1/hostel/swap-requests {target_room_id}`. Publishes
  `hostel.swap.requested`; notification-service notifies every current occupant of the
  target room (rooms can hold multiple students).
- First occupant to accept — `POST /api/v1/hostel/swap-requests/{id}/accept` — becomes
  the acceptor (DB-level guard so only the first accept wins; later ones get 409).
- Warden reviews `status=accepted` requests and approves or rejects manually — no
  automatic gender/capacity re-check, that judgment is left to the warden.
- Approve: atomically swaps the `room` FK on both `Allocation` rows. No
  `occupied_count` change, no new invoice or saga — they already paid for a room, just
  a different one now.

---

## Observability & CI

- **Metrics:** all 13 Django services expose `/metrics` (via `django-prometheus` —
  `django_prometheus` in `INSTALLED_APPS`, the Before/After middleware pair, and
  `path("", include("django_prometheus.urls"))`). ai-service is FastAPI and is not
  scraped. Prometheus (`infra/prometheus/`) scrapes every Django service — 14 targets
  including itself, all healthy; Grafana (`infra/grafana/`) ships a dashboard for request
  rate, latency, error rate, and per-tenant request count — see
  [Monitoring under load](#monitoring-under-load) for it running against real traffic.
  Both sit behind the `observability` compose profile, so they stay off unless asked for:
  `docker compose -f infra/docker-compose.yml --profile observability up -d prometheus grafana`.
  Prometheus at `http://localhost:9090`, Grafana at `http://localhost:3000`
  (admin/admin). Note: Grafana publishes `3000`, the same port as the Next.js dev
  server — run one at a time locally, or remap one of them.
- **CI:** GitHub Actions (`.github/workflows/ci.yml`) runs a matrix over the services —
  `ruff`/`black`/`isort` → `pytest --cov` (fails under 70%) → `bandit`/`pip-audit` →
  `docker build` — with ephemeral Postgres/Redis service containers for the test step.

---

## Recent changes

- Admin can now view all users in their tenant and bulk-deactivate (soft-delete) selected accounts from **Admin → Users**. Deactivated users are kept in the database (not hard-deleted) and can no longer sign in. Self-delete and removing the tenant's last active admin are blocked server-side.

---

## License

MIT — see [LICENSE](LICENSE).
