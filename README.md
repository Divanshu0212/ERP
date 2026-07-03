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
| student-service      | Student master records                          | `/api/v1/students/`      | Django  | stub   |
| attendance-service   | Attendance tracking                             | `/api/v1/attendance/`    | Django  | stub   |
| exam-service         | Exams & results                                 | `/api/v1/exams/`         | Django  | stub   |
| library-service      | Books & lending                                 | `/api/v1/books/`         | Django  | stub   |
| canteen-service      | Menu & orders                                   | `/api/v1/menu-items/`    | Django  | stub   |
| placement-service    | Placement drives                                | `/api/v1/placements/`    | Django  | stub   |
| analytics-service    | Cross-service metrics                           | `/api/v1/metrics/`       | Django  | stub   |

"stub" services expose working CRUD prototypes on the tenant/JWT/event foundation;
the seven "full" services carry the complete business logic and the two demo flows.

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

---

## Observability & CI

- **Metrics:** each Django service exposes `/metrics` (via `django-prometheus`).
  Prometheus (`infra/prometheus/`) scrapes all services; Grafana (`infra/grafana/`)
  ships a dashboard for request rate, latency, error rate, and per-tenant request count.
  Prometheus at `http://localhost:9090`, Grafana at `http://localhost:3000`
  (admin/admin). Note: Grafana publishes `3000`, the same port as the Next.js dev
  server — run one at a time locally, or remap one of them.
- **CI:** GitHub Actions (`.github/workflows/ci.yml`) runs a matrix over the services —
  `ruff`/`black`/`isort` → `pytest --cov` (fails under 70%) → `bandit`/`pip-audit` →
  `docker build` — with ephemeral Postgres/Redis service containers for the test step.
