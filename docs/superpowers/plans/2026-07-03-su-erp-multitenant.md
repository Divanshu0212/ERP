# SU-ERP Multi-Tenant University ERP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-tenant, event-driven microservices university ERP (Django/DRF + FastAPI + Next.js) that scales to thousands of concurrent students across many institutions.

**Architecture:** DB-per-service microservices behind an Nginx gateway. Shared-DB row-level `tenant_id` multi-tenancy. Zero-trust JWT (each service verifies signatures itself). Event-driven choreography over RabbitMQ with a transactional outbox and idempotent consumers. One real saga (hostel allocation ↔ finance). Rule-based ML in a FastAPI `ai-service`.

**Tech Stack:** Django 5 + DRF, FastAPI, PostgreSQL + PgBouncer, Redis, RabbitMQ (pika), Celery, `djangorestframework-simplejwt`, `django-environ`/`dj-database-url`, `drf-spectacular`, Docker Compose, Next.js (App Router) + Tailwind, pytest.

## Global Constraints

- Python 3.12; Django 5.x; DRF 3.15+.
- Every tenant-owned table has an indexed `tenant_id` UUID column. No queryset touches tenant data without a tenant filter (enforced by `TenantManager`).
- No service connects to another service's database. Cross-service references are UUID `*_id` fields; cross-service data flows via REST (through gateway) or events.
- JWT is HS256 with shared `JWT_SIGNING_KEY`. Services read `role`/`tenant`/`sub` from **token claims only**, never from `X-User-*` headers.
- Every state-changing event is written to `OutboxEvent` in the same DB transaction as the state change; a Celery-beat task drains it. Every consumer is idempotent via `ProcessedEvent`.
- API responses use the envelope `{ "success": bool, "data": any, "message": str, "errors": any }`. URL versioning `/api/v1/...`. Pagination default 20, max 100.
- Config from env via `django-environ`; `DATABASE_URL`/`REDIS_URL`/`RABBITMQ_URL`/`JWT_SIGNING_KEY` with local-Docker fallbacks. No secrets in code.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.

---

## Phase 0 — Repo Scaffold

### Task 0.1: Monorepo skeleton & tooling

**Files:**
- Create: `pyproject.toml` (root, ruff/black/isort/pytest config), `README.md`, `.env.example`, `Makefile`
- Create: `services/`, `shared/libs/`, `shared/event-schemas/`, `frontend/`, `infra/`, `.github/workflows/` (empty `.gitkeep`s)

**Interfaces:**
- Produces: root dev tooling config used by every service (`ruff`, `black`, `isort`, `pytest` defaults).

- [ ] **Step 1: Create root `pyproject.toml`**

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.black]
line-length = 100

[tool.isort]
profile = "black"
line_length = 100

[tool.pytest.ini_options]
DJANGO_SETTINGS_MODULE = "config.settings"
python_files = ["test_*.py", "tests.py"]
addopts = "-q"
```

- [ ] **Step 2: Create `Makefile` with common targets**

```makefile
.PHONY: up down test lint fmt
up:        ; docker compose -f infra/docker-compose.yml up --build
down:      ; docker compose -f infra/docker-compose.yml down -v
lint:      ; ruff check services shared && black --check services shared && isort --check services shared
fmt:       ; ruff check --fix services shared && black services shared && isort services shared
test:      ; pytest services shared
```

- [ ] **Step 3: Create `.env.example`** documenting every env var (DATABASE_URL, REDIS_URL, RABBITMQ_URL, JWT_SIGNING_KEY, DEBUG) with local-Docker default values commented.

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "chore: monorepo skeleton and tooling"
```

---

## Phase 1 — `suerp_common` Shared Library

This installable package is imported by every Django service. Build it fully with tests before any service depends on it.

**File structure for the package:**
```
shared/libs/suerp_common/
├── pyproject.toml
├── suerp_common/
│   ├── __init__.py
│   ├── tenancy.py        # tenant context var, middleware, TenantManager, TenantModel base
│   ├── auth.py           # JWT authentication + role/tenant claim extraction
│   ├── permissions.py    # RBAC + object-owner + tenant-required permissions
│   ├── envelope.py       # response envelope + DRF exception handler + pagination
│   ├── outbox.py         # OutboxEvent model, publish_event(), drain task helper
│   ├── inbox.py          # ProcessedEvent model, idempotent consumer decorator
│   └── events.py         # RabbitMQ publisher/consumer (pika), event envelope builder
└── tests/
```

### Task 1.1: Tenant context & TenantManager

**Files:**
- Create: `shared/libs/suerp_common/suerp_common/tenancy.py`
- Test: `shared/libs/suerp_common/tests/test_tenancy.py`

**Interfaces:**
- Produces:
  - `set_current_tenant(tenant_id: str | None) -> None`
  - `get_current_tenant() -> str | None`
  - `class TenantManager(models.Manager)` — `get_queryset()` filters by `get_current_tenant()`
  - `class TenantModel(models.Model)` — abstract; adds `tenant_id = UUIDField(db_index=True)`, `objects = TenantManager()`, `all_objects = models.Manager()`

- [ ] **Step 1: Write the failing test**

```python
import uuid
from suerp_common.tenancy import set_current_tenant, get_current_tenant

def test_tenant_context_roundtrip():
    tid = str(uuid.uuid4())
    set_current_tenant(tid)
    assert get_current_tenant() == tid
    set_current_tenant(None)
    assert get_current_tenant() is None
```

- [ ] **Step 2: Run test, verify it fails** — `pytest shared/libs/suerp_common/tests/test_tenancy.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement `tenancy.py`**

```python
import contextvars
from django.db import models

_current_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_tenant", default=None
)

def set_current_tenant(tenant_id: str | None) -> None:
    _current_tenant.set(tenant_id)

def get_current_tenant() -> str | None:
    return _current_tenant.get()


class TenantManager(models.Manager):
    def get_queryset(self):
        qs = super().get_queryset()
        tenant = get_current_tenant()
        if tenant is None:
            return qs
        return qs.filter(tenant_id=tenant)


class TenantModel(models.Model):
    import uuid as _uuid
    tenant_id = models.UUIDField(db_index=True)
    objects = TenantManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True
```

- [ ] **Step 4: Run test, verify it passes.**

- [ ] **Step 5: Add test for manager filtering** (uses a dummy model in a test app) asserting a queryset for tenant A excludes tenant B rows, and `all_objects` returns both. Run and pass.

- [ ] **Step 6: Commit** — `git commit -m "feat(common): tenant context and TenantManager"`

### Task 1.2: TenantMiddleware (resolve tenant from JWT claim / subdomain)

**Files:**
- Modify: `shared/libs/suerp_common/suerp_common/tenancy.py` (append middleware)
- Test: `shared/libs/suerp_common/tests/test_tenant_middleware.py`

**Interfaces:**
- Consumes: `set_current_tenant`.
- Produces: `class TenantMiddleware` — reads `request.auth`/decoded JWT `tenant` claim (set by auth backend) else the request subdomain; calls `set_current_tenant`; clears it in a `finally`.

- [ ] **Step 1: Failing test** — request with `tenant` claim sets context; request without clears to None after response.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement `TenantMiddleware`** reading `getattr(request, "tenant_id", None)` (populated by auth backend, Task 1.3) with subdomain fallback `request.get_host().split(".")[0]`; wrap `get_response` in try/finally that always `set_current_tenant(None)`.
- [ ] **Step 4: Run, pass.**
- [ ] **Step 5: Commit.**

### Task 1.3: JWT auth backend (zero-trust)

**Files:**
- Create: `shared/libs/suerp_common/suerp_common/auth.py`
- Test: `shared/libs/suerp_common/tests/test_auth.py`

**Interfaces:**
- Produces:
  - `class JWTAuthentication(BaseAuthentication)` — verifies HS256 signature with `settings.JWT_SIGNING_KEY`, returns `(SimpleUser(id, role, tenant), claims)`; sets `request.tenant_id`.
  - `class SimpleUser` — `.id`, `.role`, `.tenant_id`, `.is_authenticated = True`.

- [ ] **Step 1: Failing test** — a token signed with the key decodes to a `SimpleUser` with correct `role`/`tenant`; a token signed with a wrong key raises `AuthenticationFailed`; **a request with only `X-User-Role: admin` header and no token is unauthenticated** (proves headers carry no authority).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** using `pyjwt`: parse `Authorization: Bearer`, `jwt.decode(..., algorithms=["HS256"])`, build `SimpleUser`, set `request.tenant_id = claims["tenant"]`. On any header-only/no-bearer case return `None` (anonymous).
- [ ] **Step 4: Run, pass.**
- [ ] **Step 5: Commit.**

### Task 1.4: Permissions (RBAC, tenant-required, object-owner)

**Files:**
- Create: `shared/libs/suerp_common/suerp_common/permissions.py`
- Test: `.../tests/test_permissions.py`

**Interfaces:**
- Produces:
  - `def role_required(*roles)` → returns a `BasePermission` subclass allowing only listed roles (reads `request.user.role`).
  - `class TenantRequired(BasePermission)` — denies if `get_current_tenant()` is None.
  - `class IsObjectOwner(BasePermission)` — `has_object_permission` true if `obj.owner_id == request.user.id` or role in {admin}.

- [ ] **Step 1: Failing test** — warden-only permission allows warden, 403s student; `TenantRequired` denies when no tenant; owner permission allows owner, denies non-owner.
- [ ] **Step 2–4: Implement, run, pass.**
- [ ] **Step 5: Commit.**

### Task 1.5: Response envelope, exception handler, pagination

**Files:**
- Create: `shared/libs/suerp_common/suerp_common/envelope.py`
- Test: `.../tests/test_envelope.py`

**Interfaces:**
- Produces:
  - `def ok(data=None, message="") -> Response` and `def fail(message, errors=None, status=400) -> Response`.
  - `def exception_handler(exc, context)` — wraps DRF's default handler output in the envelope.
  - `class StandardPagination(PageNumberPagination)` — `page_size=20`, `max_page_size=100`, envelope-shaped `get_paginated_response`.

- [ ] **Step 1: Failing test** — `ok({"a":1})` → `{"success":True,"data":{"a":1},"message":"","errors":None}`; handler turns a `ValidationError` into `success=False` with `errors` populated.
- [ ] **Step 2–4: Implement, run, pass.**
- [ ] **Step 5: Commit.**

### Task 1.6: Event envelope + RabbitMQ publisher/consumer

**Files:**
- Create: `shared/libs/suerp_common/suerp_common/events.py`
- Test: `.../tests/test_events.py`

**Interfaces:**
- Produces:
  - `def build_event(type: str, tenant_id: str, payload: dict) -> dict` → `{event_id, type, tenant_id, occurred_at, payload}`.
  - `def publish_to_broker(event: dict) -> None` — publishes JSON to exchange `suerp.events` with routing key `event["type"]` (pika, `RABBITMQ_URL`).
  - `def make_consumer(routing_keys: list[str], handler: Callable[[dict], None])` — declares a queue bound to those keys on `suerp.events`, dispatches messages to `handler`; on unhandled exception nacks to DLQ.

- [ ] **Step 1: Failing test** — `build_event(...)` has a UUID `event_id`, ISO `occurred_at`, and echoes type/tenant/payload. (Broker calls are mocked via `pika` patching; assert `basic_publish` called with routing_key == type.)
- [ ] **Step 2–4: Implement, run, pass.**
- [ ] **Step 5: Commit.**

### Task 1.7: Transactional outbox

**Files:**
- Create: `shared/libs/suerp_common/suerp_common/outbox.py`
- Test: `.../tests/test_outbox.py`

**Interfaces:**
- Consumes: `build_event`, `publish_to_broker`.
- Produces:
  - `class OutboxEvent(models.Model)` — `id(uuid)`, `type`, `tenant_id`, `payload(JSON)`, `created_at`, `published_at(null)`.
  - `def publish_event(type: str, tenant_id: str, payload: dict) -> None` — creates an `OutboxEvent` row (call inside the caller's `transaction.atomic()`).
  - `def drain_outbox(batch=100) -> int` — selects unpublished rows `FOR UPDATE SKIP LOCKED`, publishes each via `publish_to_broker`, stamps `published_at`; returns count. (Wired to Celery beat per service.)

- [ ] **Step 1: Failing test** — calling `publish_event` inside `transaction.atomic()` that then rolls back leaves **zero** outbox rows (proves same-transaction semantics); on commit exactly one unpublished row exists; `drain_outbox` publishes it and marks `published_at`.
- [ ] **Step 2–4: Implement, run, pass.**
- [ ] **Step 5: Commit.**

### Task 1.8: Idempotent consumer (inbox)

**Files:**
- Create: `shared/libs/suerp_common/suerp_common/inbox.py`
- Test: `.../tests/test_inbox.py`

**Interfaces:**
- Produces:
  - `class ProcessedEvent(models.Model)` — `event_id(uuid, unique)`, `processed_at`.
  - `def idempotent(handler)` — decorator: if `event["event_id"]` already in `ProcessedEvent`, return without re-running; else run handler and record it, atomically.

- [ ] **Step 1: Failing test** — a handler wrapped with `idempotent` runs once for a given `event_id`; a second delivery of the same `event_id` does **not** re-run it (assert side-effect counter == 1).
- [ ] **Step 2–4: Implement, run, pass.**
- [ ] **Step 5: Commit — `git commit -m "feat(common): outbox and idempotent inbox"`**

### Task 1.9: Package the library

**Files:**
- Create: `shared/libs/suerp_common/pyproject.toml`

- [ ] **Step 1:** Write `pyproject.toml` (name `suerp-common`, deps: `django`, `djangorestframework`, `pyjwt`, `pika`). Installable via `pip install -e ./shared/libs/suerp_common`.
- [ ] **Step 2:** Run full package test suite `pytest shared/libs/suerp_common -v` → all pass.
- [ ] **Step 3: Commit.**

---

## Phase 2 — Infra (local full stack)

### Task 2.1: docker-compose base stack

**Files:**
- Create: `infra/docker-compose.yml`, `infra/pgbouncer/pgbouncer.ini`, `infra/prometheus/prometheus.yml`

**Interfaces:**
- Produces: named services `postgres`, `pgbouncer`, `redis`, `rabbitmq`, `prometheus`, `grafana` reachable on a shared `suerp-net` network; env-var contract each Django service will consume (`DATABASE_URL` pointing at `pgbouncer:6432`).

- [ ] **Step 1:** Write `docker-compose.yml` with: `postgres:16` (multiple DBs via init script `services/*`), `pgbouncer` (transaction mode) in front, `redis:7`, `rabbitmq:3-management`, `prometheus`, `grafana`. Healthchecks on postgres/rabbitmq.
- [ ] **Step 2:** Add a Postgres init script creating one database per service (`auth`, `hostel`, `finance`, `transport`, `grievance`, `notification`).
- [ ] **Step 3: Verify** `docker compose -f infra/docker-compose.yml up -d postgres pgbouncer redis rabbitmq` → all healthy (`docker compose ps`).
- [ ] **Step 4: Commit.**

---

## Phase 3 — `auth-service` (issues the tenant claim)

**Service file structure (template every Django service follows):**
```
services/auth-service/
├── Dockerfile
├── requirements.txt
├── manage.py
├── .env.example
├── config/            # settings.py, urls.py, celery.py, wsgi.py
└── accounts/          # models, serializers, views, permissions, urls, tests, consumers, tasks
```

### Task 3.1: Service bootstrap (settings wired to suerp_common)

**Files:**
- Create: `services/auth-service/config/settings.py`, `config/urls.py`, `config/celery.py`, `manage.py`, `requirements.txt`, `Dockerfile`, `.env.example`

**Interfaces:**
- Produces: a runnable Django project where `REST_FRAMEWORK` uses `suerp_common` auth/exception-handler/pagination, `MIDDLEWARE` includes `TenantMiddleware`, DB from `dj_database_url.parse(env("DATABASE_URL"))`, Celery app configured from `REDIS_URL`.

- [ ] **Step 1:** Write `requirements.txt` (django, djangorestframework, drf-spectacular, djangorestframework-simplejwt, django-environ, dj-database-url, celery, redis, psycopg[binary], -e shared lib).
- [ ] **Step 2:** Write `settings.py`: env-driven; `DEFAULT_AUTHENTICATION_CLASSES=["suerp_common.auth.JWTAuthentication"]`, `EXCEPTION_HANDLER`, `DEFAULT_PAGINATION_CLASS`, `TenantMiddleware`, `DATABASES` (default + `read_db` alias), `JWT_SIGNING_KEY=env("JWT_SIGNING_KEY")`, `django-prometheus` apps + middleware.
- [ ] **Step 3:** Write `config/celery.py` and a smoke test: `pytest` collects, `python manage.py check` passes.
- [ ] **Step 4: Commit.**

### Task 3.2: Institution (tenant) & User models

**Files:**
- Create: `services/auth-service/accounts/models.py`
- Test: `services/auth-service/accounts/tests/test_models.py`

**Interfaces:**
- Produces:
  - `class Institution(models.Model)` — `id(uuid)`, `slug(unique)`, `name`, `is_active`.
  - `class User(AbstractBaseUser)` — `id(uuid)`, `tenant_id(FK-ref uuid to Institution)`, `email`, `role` (choices), `is_active`; unique on `(tenant_id, email)`.
  - `class LoginAudit(models.Model)` — `user_id`, `tenant_id`, `ip`, `success`, `timestamp`.

- [ ] **Step 1: Failing test** — two users with the same email but different `tenant_id` can both exist; same email + same tenant violates the unique constraint.
- [ ] **Step 2–4:** Implement models + migration, run, pass.
- [ ] **Step 5: Commit.**

### Task 3.3: Registration & login (JWT with tenant claim)

**Files:**
- Create: `services/auth-service/accounts/serializers.py`, `accounts/views.py`, `accounts/urls.py`
- Test: `accounts/tests/test_auth_flow.py`

**Interfaces:**
- Consumes: `Institution`, `User`, `envelope.ok/fail`.
- Produces endpoints: `POST /api/v1/auth/register`, `POST /api/v1/auth/login` (returns access+refresh; **access token embeds `tenant` claim = user's institution**), `POST /api/v1/auth/refresh`, `GET /api/v1/auth/me`.

- [ ] **Step 1: Failing test** — register under institution A, log in, decode access token → claims contain `role` and `tenant == A.id`; `GET /auth/me` with that token returns the user; wrong password increments `LoginAudit` failure and after 5 failures returns locked (429/403).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** serializers + views; customize SimpleJWT token to inject `tenant` and `role` claims; lockout via `LoginAudit` count in the last N minutes.
- [ ] **Step 4: Run, pass.**
- [ ] **Step 5: Commit — `git commit -m "feat(auth): registration, login, tenant-scoped JWT"`**

### Task 3.4: `user.registered` outbox event + provisioning endpoint

**Files:**
- Modify: `accounts/views.py`; Create: `accounts/tasks.py` (celery beat drain wired to `drain_outbox`)
- Test: `accounts/tests/test_events.py`

**Interfaces:**
- Produces: on successful register, `publish_event("user.registered", tenant, {user_id, role})` inside the same transaction; a beat task calling `drain_outbox`.

- [ ] **Step 1: Failing test** — after register, exactly one unpublished `OutboxEvent` of type `user.registered` exists with correct tenant/payload.
- [ ] **Step 2–4:** Implement (wrap create+publish in `transaction.atomic()`), run, pass.
- [ ] **Step 5: Commit.**

---

## Phase 4 — The Saga Pair: `finance-service` + `hostel-service`

Both services bootstrap from the Task 3.1 template (settings wired to `suerp_common`, own DB, own Celery). Each service's first task is "bootstrap from template" (mirror Task 3.1 — repeat the settings, requirements, Dockerfile, celery.py for this service's DB; do not reference Task 3.1 by number, copy the content).

### Task 4.1: finance bootstrap
Mirror Task 3.1 for `services/finance-service/` (DB `finance`, app `billing`). Commit.

### Task 4.2: finance models
**Files:** `services/finance-service/billing/models.py`; Test: `.../tests/test_models.py`
**Interfaces:** Produces `FeeStructure`, `Invoice(TenantModel: student_id, amount, status[pending/paid/failed], purpose, idempotency_key null)`, `Payment(invoice_id, amount, status, gateway_ref)`, `Receipt`.
- [ ] Failing test: an `Invoice` requires a `tenant_id`; `Invoice.objects` for tenant A excludes tenant B. Implement, run, pass, commit.

### Task 4.3: simulated payment gateway (swappable)
**Files:** `billing/gateway.py`; Test: `.../tests/test_gateway.py`
**Interfaces:** Produces `class PaymentGateway(Protocol): def charge(amount, idempotency_key) -> ChargeResult` and `class SimulatedGateway` (deterministic: amount ending in `.00` succeeds, `.99` fails — documented test hook).
- [ ] Failing test: `SimulatedGateway().charge(100.00, key)` → success; `charge(9.99, key)` → failure; same key twice returns the same result (idempotent). Implement, run, pass, commit.

### Task 4.4: pay endpoint + `finance.payment.success/failed` event (outbox)
**Files:** `billing/views.py`, `billing/serializers.py`, `billing/urls.py`; Test: `.../tests/test_pay.py`
**Interfaces:** Produces `POST /api/v1/finance/invoices`, `POST /api/v1/finance/pay` (body: invoice_id, idempotency_key), `GET /api/v1/finance/invoices`.
- [ ] **Step 1: Failing test** — paying a pending invoice with a `.00` amount: invoice→`paid`, a `Payment` row created, and one `OutboxEvent` `finance.payment.success` with `{invoice_id, student_id, purpose}` — all in one transaction. A `.99` invoice → `failed` + `finance.payment.failed` event. Replaying the same idempotency_key does not double-charge or double-emit.
- [ ] Steps 2–4: Implement, run, pass.
- [ ] Step 5: Commit.

### Task 4.5: finance consumes `hostel.allocation.requested` → creates invoice
**Files:** `billing/consumers.py`; Test: `.../tests/test_consumer.py`
**Interfaces:** Produces an idempotent consumer bound to `hostel.allocation.requested` that creates a hostel-fee `Invoice` and emits `finance.invoice.created`.
- [ ] Failing test: delivering a `hostel.allocation.requested` event creates exactly one pending Invoice for that student/tenant; redelivery (same event_id) creates none extra (idempotent). Implement, run, pass, commit.

### Task 4.6–4.8: hostel bootstrap, models, allocate endpoint
- **4.6:** Bootstrap `services/hostel-service/` (DB `hostel`, app `hostel`) from the template. Commit.
- **4.7:** Models `Block`, `Room(capacity, occupied_count, is_available)`, `Allocation(TenantModel: room_id, student_id, status[pending/confirmed/released])`, `LeaveRequest`, `Complaint`. Failing test: room `is_available` false at capacity; allocation tenant-isolated. Implement, run, pass, commit.
- **4.8:** `POST /api/v1/hostel/allocate` — reserves room (`occupied_count++`, allocation `pending`) and emits `hostel.allocation.requested` in one transaction. Failing test: allocating a full room 400s; allocating an available room creates a pending allocation + one outbox event, increments occupied_count. Implement, run, pass, commit.

### Task 4.9: hostel confirms on `finance.payment.success`; releases on failure/timeout
**Files:** `hostel/consumers.py`, `hostel/tasks.py`; Test: `.../tests/test_saga.py`
**Interfaces:** Produces idempotent consumers for `finance.payment.success` (→ allocation `confirmed`, emit `hostel.allocation.confirmed`) and `finance.payment.failed` (→ release room, allocation `released`); a Celery-beat `release_stale_pending_allocations()` that releases allocations pending > timeout.
- [ ] **Step 1: Failing saga test** — simulate the full choreography in-process: allocate → assert pending + outbox `allocation.requested`; feed that event to finance consumer → assert invoice; pay → assert `payment.success`; feed to hostel consumer → assert allocation `confirmed`. Then a separate test: feed `payment.failed` → room released, `occupied_count` decremented.
- [ ] **Step 2: Timeout test** — a `pending` allocation older than the timeout is released by `release_stale_pending_allocations()`; a fresh one is not.
- [ ] Steps 3–4: Implement, run, pass.
- [ ] Step 5: Commit — `git commit -m "feat(saga): hostel allocation confirm/release via finance events"`

---

## Phase 5 — `notification-service` (event fan-out + inbox)

### Task 5.1: bootstrap (from template). Commit.
### Task 5.2: models & inbox endpoint
**Files:** `notify/models.py`, `notify/views.py`, `notify/urls.py`; Test.
**Interfaces:** `Notification(TenantModel: user_id, title, body, read, created_at)`; `GET /api/v1/notify/inbox` (current user, tenant-scoped, paginated).
- [ ] Failing test: inbox returns only the requesting user's notifications within their tenant. Implement, run, pass, commit.
### Task 5.3: fan-out consumer
**Files:** `notify/consumers.py`; Test.
**Interfaces:** idempotent consumer bound to `finance.payment.success`, `hostel.allocation.confirmed`, `grievance.scored` → writes a `Notification` for the relevant user.
- [ ] Failing test: delivering `finance.payment.success` creates one Notification for that student; redelivery creates none extra. Implement, run, pass, commit.

---

## Phase 6 — `transport-service` & `grievance-service`

### Task 6.1–6.3: transport
- **6.1** bootstrap. Commit.
- **6.2** models `Route`, `Stop`, `BusSchedule`, `Booking(TenantModel)`, `Pass`; seat-availability cached in Redis (tenant-namespaced key, 30s TTL). Failing test: booking decrements available seats; double-book of same seat 400s (idempotency key). Implement, run, pass, commit.
- **6.3** endpoints `GET /transport/routes`, `GET /transport/routes/{id}/seats`, `POST /transport/bookings`, and an idempotent consumer for `finance.payment.success` that activates a seasonal `Pass`. Failing test + implement + pass + commit.

### Task 6.4–6.6: grievance
- **6.4** bootstrap. Commit.
- **6.5** models `Ticket(TenantModel: raised_by, category, description, sentiment_score null, urgency null, status, assigned_to null)`, `TicketComment`. Endpoint `POST /api/v1/grievance` emits `grievance.created` (outbox) with `{ticket_id, text}`. Failing test: creating a ticket emits one event; ticket tenant-isolated. Implement, run, pass, commit.
- **6.6** idempotent consumer for `grievance.scored` → writes `sentiment_score`/`urgency`; if urgency ∈ {high, critical}, set status `escalated`, `assigned_to` = warden, emit nothing further (notification-service already consumes `grievance.scored`). Failing test: a `grievance.scored` with urgency=critical escalates the ticket and sets assignee; low urgency does not. Implement, run, pass, commit.

---

## Phase 7 — `ai-service` (FastAPI, rule-based ML)

**File structure:**
```
services/ai-service/
├── Dockerfile
├── requirements.txt          # fastapi, uvicorn, vaderSentiment, pika, pyjwt, scikit-learn
├── app/
│   ├── main.py               # FastAPI app, routes
│   ├── sentiment.py          # VADER + keyword urgency
│   ├── chatbot.py            # intent classify + entity slots + service routing
│   ├── consumer.py           # consumes grievance.created, emits grievance.scored
│   └── auth.py               # JWT verify (mirrors suerp_common contract)
└── tests/
```

### Task 7.1: bootstrap FastAPI + healthcheck
- [ ] Failing test (`httpx`/`TestClient`): `GET /health` → 200 `{"status":"ok"}`. Implement, run, pass, commit.

### Task 7.2: sentiment + urgency
**Files:** `app/sentiment.py`, route in `main.py`; Test.
**Interfaces:** `def score(text) -> {sentiment: float, urgency: str}`; `POST /ai/sentiment`.
- [ ] **Step 1: Failing test** — `"the warden is threatening me, this is ragging"` → urgency `critical` (keyword rule) and negative sentiment; `"the mess food was okay"` → urgency `low`, neutral-ish sentiment.
- [ ] Steps 2–4: VADER polarity + a keyword table (ragging/harassment/threat/safety → critical; broken/leak/delay → medium). Run, pass.
- [ ] Step 5: Commit.

### Task 7.3: grievance consumer → `grievance.scored`
**Files:** `app/consumer.py`; Test.
**Interfaces:** consumes `grievance.created`, runs `score`, publishes `grievance.scored` `{ticket_id, sentiment, urgency}` (same event envelope/exchange).
- [ ] Failing test: feeding a `grievance.created` with ragging text publishes one `grievance.scored` event with urgency critical. Implement, run, pass, commit.

### Task 7.4: chatbot intent routing
**Files:** `app/chatbot.py`, route; Test.
**Interfaces:** `POST /ai/chatbot/query {text}` → classifies intent (bus_time/library_fine/mess_menu/fallback via TF-IDF+LinearSVC over a small seed set), extracts entities, calls the owning service's API through the gateway, returns a templated NL answer. External calls mocked in tests.
- [ ] **Step 1: Failing test** — `"when is my next bus"` → intent `bus_time`, calls transport API (mocked), returns a string containing the mocked departure time; unknown query → fallback message. Implement, run, pass, commit.

---

## Phase 8 — Stubbed Services

### Task 8.1: stub generator
For each of `student`, `attendance`, `exam`, `library`, `canteen`, `placement`, `analytics`: bootstrap from template + one tenant-aware CRUD model + one list/create endpoint + a smoke test (`GET` returns 200 empty paginated envelope; created row is tenant-isolated). One commit per service. These are explicitly marked "prototype-level" in each service README.

---

## Phase 9 — Gateway

### Task 9.1: Nginx gateway config
**Files:** `gateway/nginx.conf`, `gateway/Dockerfile`, add `gateway` to `infra/docker-compose.yml`.
**Interfaces:** routes `/api/v1/auth/*`→auth, `/api/v1/hostel/*`→hostel, etc.; `limit_req` zones for per-IP rate limiting; gzip/brotli; passes `Authorization` through unchanged; adds `X-Request-Id`.
- [ ] **Step 1:** Write `nginx.conf` with upstreams per service and `location` routing; a `limit_req_zone` (e.g., 10r/s burst 20) and a stricter zone on `/auth/login`.
- [ ] **Step 2: Verify** with the stack up: `curl` through `localhost:8080/api/v1/auth/login` reaches auth-service; a burst of login requests gets `429`. 
- [ ] **Step 3: Commit.**

---

## Phase 10 — Frontend (Next.js)

**File structure:** `frontend/su-erp-web/` — App Router, `lib/api.ts` (fetch wrapper adding `Authorization`, hitting gateway), `lib/auth.ts` (token store), route groups per role.

### Task 10.1: bootstrap Next.js + Tailwind + API client
- [ ] Scaffold app, Tailwind, `lib/api.ts` (reads gateway base URL from env, attaches bearer token, unwraps the `{success,data}` envelope, throws on `success:false`). Smoke test: `npm run build` passes. Commit.

### Task 10.2: login + tenant-aware session
- [ ] Login page posts to `/api/v1/auth/login`, stores tokens, decodes role+tenant for routing. Playwright/RTL test: successful login redirects to role dashboard; failed login shows envelope error message. Commit.

### Task 10.3: role dashboards (student, warden, admin)
- [ ] Student: fees/invoices + pay button (drives the saga), transport booking, raise-grievance, notification inbox. Warden: pending hostel allocations, escalated grievances. Admin: cross-service counts. Each view calls the gateway and renders the envelope. Component tests per view. Commit per dashboard.

### Task 10.4: saga + escalation demo pages
- [ ] A "pay hostel fee" flow that visibly transitions allocation pending→confirmed (polls hostel API), and a grievance page that shows urgency after ML scoring. Test the polling/refresh logic with mocked API. Commit.

---

## Phase 11 — CI, Observability, Docs

### Task 11.1: GitHub Actions CI
**Files:** `.github/workflows/ci.yml`.
- [ ] Matrix over services: `ruff`/`black`/`isort` → `pytest --cov` (fail <70%) → `bandit`/`pip-audit` → `docker build`. Ephemeral Postgres/Redis service containers for tests. Commit.

### Task 11.2: Prometheus + Grafana wiring
- [ ] Each Django service exposes `/metrics` (`django-prometheus`); `infra/prometheus/prometheus.yml` scrapes all services; a Grafana dashboard JSON (request rate, latency, error rate, per-tenant request count). Verify metrics scrape locally. Commit.

### Task 11.3: README + demo script + event-schemas
- [ ] Root `README.md` (architecture, how to run, how to demo the saga and ML escalation), `shared/event-schemas/*.json` (JSON Schema per event type), per-service `.env.example`. Commit.

---

## Self-Review

**Spec coverage:** §2 scope → Phases 3–10; §4 multi-tenancy → Tasks 1.1–1.2, TenantModel used in every model task; §5 zero-trust JWT → Task 1.3 (incl. header-spoofing test); §6 events/outbox/inbox → Tasks 1.6–1.8; §7 saga → Tasks 4.4–4.9; §8 scale (PgBouncer/Redis/read_db) → Task 2.1, 3.1, 6.2; §9 ML → Phase 7; §10 layout → Phase 0; §11 API standards → Task 1.5; §12 testing incl. cross-tenant isolation → every model task's isolation test + saga tests; §13 error handling → Task 1.5 + DLQ in 1.6. All covered.

**Placeholder scan:** No TBD/TODO. "Mirror Task 3.1" instances explicitly say to copy content, not reference — acceptable per the DRY-with-repeated-code rule for out-of-order reading.

**Type consistency:** `publish_event(type, tenant_id, payload)` used identically in outbox (1.7) and all producers (3.4, 4.4, 4.8, 6.5); `make_consumer`/`idempotent` used consistently in all consumers; envelope `ok/fail` consistent across services; `TenantModel`/`TenantManager` names consistent. Consistent.
