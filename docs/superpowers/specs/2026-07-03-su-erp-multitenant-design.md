# SU-ERP — Multi-Tenant University ERP: Design Spec

**Date:** 2026-07-03
**Status:** Approved design → implementation
**Supersedes framing of:** `University_ERP_Capstone_Documentation.md` (the "$0 single-college free-tier demo" framing is replaced by production multi-tenant scale; the module/service catalogue and ML catalogue from that doc are retained.)

---

## 1. Goal & Non-Negotiables

Build **SU-ERP**, a multi-tenant SaaS university ERP sold to many institutions, serving **thousands of concurrent students simultaneously**. Microservices, event-driven, ML-assisted.

Non-negotiables driven by scale:
- Stateless, horizontally scalable services (JWT carries all identity; no server session state).
- Hard tenant isolation — no query may leak across institutions.
- Bounded DB connections under thousands of workers (PgBouncer).
- Async offload of everything not on the request/response critical path.
- At-least-once event delivery with idempotent consumers (no lost saga steps).

## 2. Scope This Pass

**Fully built** (CRUD + JWT auth + events + tenant isolation):
`auth-service`, `hostel-service`, `transport-service`, `finance-service`, `grievance-service`, `notification-service`, `ai-service` (FastAPI), `gateway` (Nginx + thin auth/routing).

**Stubbed** (basic CRUD, tenant-aware, marked "designed, prototype-level"):
`student-service`, `attendance-service`, `exam-service`, `library-service`, `canteen-service`, `placement-service`, `analytics-service`.

**Frontend:** Next.js (App Router) + Tailwind; role-based dashboards; talks only to gateway.

**Two demo centerpieces:**
1. **Hostel-allocation saga** across hostel + finance + notification via events (reserve → invoice → pay → confirm/release-on-timeout).
2. **Grievance ML auto-escalation** — a complaint scored urgent by `ai-service` auto-escalates and notifies the warden.

## 3. Technology Stack

| Layer | Choice |
|---|---|
| Business services | Django 5 + DRF, one project per service |
| ML service | FastAPI (`ai-service`) — async, Pydantic ML contracts |
| Gateway | Nginx (TLS, gzip/brotli, rate-limit, LB) + thin auth-check |
| DB | PostgreSQL, DB-per-service; PgBouncer (transaction mode) pooling |
| Cache / rate-limit / Celery broker | Redis, keys namespaced by `tenant_id` |
| Event bus | RabbitMQ, topic exchange `suerp.events` |
| Async | Celery + Celery Beat (outbox drain, saga timeouts, PDFs, email, ML) |
| Auth | `djangorestframework-simplejwt`, HS256 shared signing key |
| Config | `django-environ` + `dj-database-url`; env with local Docker fallback |
| API docs | `drf-spectacular` (OpenAPI 3) per service |
| Observability | `django-prometheus` /metrics, JSON logs (`python-json-logger`) with tenant_id + request_id |
| Containers | Docker + docker-compose (full local stack) |
| CI | GitHub Actions: lint (ruff/black/isort) → test (pytest-cov, ≥70%) → security (bandit, pip-audit) → docker build |
| Frontend | Next.js App Router + Tailwind |
| Shared code | `suerp_common` installable package in `shared/libs/` |

## 4. Multi-Tenancy (shared DB, shared schema, row-level `tenant_id`)

- `auth-service` owns `Institution` (tenant). Every tenant-owned table in every service carries an indexed `tenant_id` (UUID).
- **Tenant resolution:** middleware resolves the current tenant from the JWT `tenant` claim (primary) or request subdomain (`<slug>.suerp.app`), stores it in a request-scoped context var.
- **Enforcement (defense in depth):**
  1. `TenantManager` base model manager auto-filters every queryset by the active `tenant_id`.
  2. A DRF permission/mixin 403s any tenant-scoped access with no resolved tenant.
  3. Postgres **Row-Level Security** policies on hot tables as a final backstop.
- **Rejected:** schema-per-tenant (migrations O(tenants), Postgres degrades past hundreds) and DB-per-tenant (operationally impossible at many tenants).
- Cache keys, rate-limit buckets, and event payloads all carry `tenant_id`.

## 5. Identity & Zero-Trust Auth

- Only `auth-service` issues tokens: JWT access (~15 min) + refresh (~7 days, rotated on use).
- Claims: `sub` (user_id), `role`, `tenant`, `exp`.
- **Every service independently verifies the JWT signature** with the shared `JWT_SIGNING_KEY` and reads `role`/`tenant` from *claims*. Gateway `X-User-*` headers are debug hints with **zero authority** — never trusted for authz. (Fixes the doc's header-spoofing hole.)
- RBAC via DRF permission classes on the `role` claim (student/faculty/warden/driver/admin/alumni). Object-level: users touch only their own records.
- Account lockout after N failed logins (`LoginAudit`); optional TOTP MFA for admin/warden.
- Inter-service calls (not via gateway) use short-lived service tokens (client-credentials).

## 6. Inter-Service Communication & Events

- **Sync:** REST via gateway for immediate user-facing reads/writes.
- **Async:** RabbitMQ topic exchange `suerp.events`; routing keys `finance.payment.success`, `hostel.allocation.requested`, `grievance.created`, etc.
- **Event envelope:** `{ event_id (uuid), type, tenant_id, occurred_at, payload }`.
- **Transactional outbox:** producing a state change writes an `OutboxEvent` row **in the same DB transaction**; a Celery-beat task drains outbox → RabbitMQ (at-least-once). No event lost if broker is down or process dies post-commit. (Fixes the doc's fire-after-commit gap.)
- **Idempotent consumers:** each consumer records handled `event_id` in `ProcessedEvent` and skips duplicates.
- **Dead-letter queue** for poison events; retry with exponential backoff.

## 7. The Saga — Hostel Allocation (choreography)

1. `POST /hostel/allocate` → hostel reserves room `status=pending`, emits `hostel.allocation.requested`.
2. finance consumes → creates hostel-fee `Invoice`, emits `finance.invoice.created`.
3. Student pays (`POST /finance/pay`, idempotency-keyed) → finance emits `finance.payment.success`. **Test mode = a simulated in-process payment gateway** (deterministic success/failure by amount, no real Razorpay/Stripe account); a real gateway adapter drops in behind the same interface later.
4. hostel consumes → allocation `status=confirmed`, emits `hostel.allocation.confirmed`.
5. notification consumes success/confirmed → inbox + email.
6. **Compensation:** Celery-beat timeout on pending allocations; on timeout or `finance.payment.failed`, hostel releases the room (`occupied_count--`, `status=released`).

## 8. Performance & Scale

- Stateless services, N replicas, Nginx load-balances; no sticky sessions.
- PgBouncer transaction pooling (thousands of workers → bounded connections).
- Redis read-through cache (seat availability, catalogues, dashboards; TTL 30–60s), tenant-namespaced.
- `read_db` alias in every service so a read-replica drops in via env var.
- Celery for PDFs, bulk email/SMS, ML inference, nightly aggregations.
- Idempotency keys on payment/booking POSTs.
- `select_related`/`prefetch_related`; DRF pagination (default 20, max 100); indexed FKs + `(tenant_id, <hot col>)` composite indexes.
- Gzip/brotli at gateway; batch event publishing (one summary event, not N).

## 9. ML / AI Layer (`ai-service`, FastAPI, rule-based/lightweight)

- **Sentiment + urgency** (grievance): VADER polarity + keyword/rule urgency classifier (ragging/harassment/safety → critical). Emits `grievance.scored`. No heavy model download.
- **Chatbot:** intent classification (TF-IDF + linear model) + spaCy-lite entity slots; routes to the owning service's API ("when's my next bus" → transport API) — never hallucinates.
- Stateless inference; features arrive in request payload or via API. Other ML features (resume match, attendance risk, forecasting, timetable) documented as designed / prototype-level.

## 10. Repository Layout (monorepo)

```
su-erp/
├── gateway/                 # Nginx conf + thin auth-check
├── services/
│   ├── auth-service/  hostel-service/  transport-service/
│   ├── finance-service/  grievance-service/  notification-service/
│   ├── ai-service/         # FastAPI
│   └── <stubbed services>/
├── shared/
│   ├── libs/suerp_common/   # installable: JWT auth, tenant mgr, envelope, outbox, event consumer base
│   └── event-schemas/       # JSON Schemas per event type
├── frontend/su-erp-web/     # Next.js
├── infra/
│   ├── docker-compose.yml   # full local stack: services + Postgres + PgBouncer + Redis + RabbitMQ + gateway + Prometheus/Grafana
│   ├── prometheus/  grafana/
├── .github/workflows/ci.yml
├── docs/
└── README.md
```

## 11. API Standards

- URL versioning `/api/v1/...`; plural kebab-case resources.
- Uniform envelope `{ success, data, message, errors }`; global DRF exception handler.
- `drf-spectacular` OpenAPI + Swagger UI per service.
- Pagination default 20 / max 100.

## 12. Testing

- pytest-django per service; `APIClient` integration tests.
- **Cross-tenant isolation suite:** assert tenant A cannot read/write tenant B (the highest-value safety test).
- Event publish/consume tests (mock broker); outbox drain test; idempotency (duplicate event) test.
- Saga tests: happy path + timeout compensation.
- ML: fixed inputs → asserted output ranges.
- CI gates: ruff/black/isort, coverage ≥70%, bandit, pip-audit, docker build.

## 13. Error Handling

- Uniform error envelope; global exception handler maps exceptions → envelope.
- Broker/HTTP calls: retry with exponential backoff; DLQ for poison events.
- Saga failures trigger compensating actions; all sensitive actions (fee waiver, grade change, reallocation) audit-logged with actor + tenant + before/after.

## 14. Build Order

1. `shared/libs/suerp_common` (JWT auth, tenant manager, envelope, outbox, consumer base) — everything depends on it.
2. `infra/docker-compose.yml` skeleton (Postgres, PgBouncer, Redis, RabbitMQ, gateway).
3. `auth-service` (Institution/tenant, users, JWT, RBAC) — issues the tenant claim.
4. `finance-service` + `hostel-service` — the saga pair.
5. `notification-service` — event fan-out + inbox.
6. `transport-service`, `grievance-service`.
7. `ai-service` (FastAPI) — sentiment/urgency + chatbot.
8. Stubbed services.
9. Gateway wiring + rate limiting.
10. Next.js frontend + role dashboards.
11. CI, observability, tests, README + demo script.
