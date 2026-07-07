# SU-ERP Build — Session Handoff

**Purpose:** Continue building the SU-ERP multi-tenant university ERP in a fresh session. This file is the complete context + resume prompt. Paste the "Resume Prompt" section into the new session.

---

## 1. What this project is

Multi-tenant SaaS university ERP (sell to many institutions, thousands of concurrent students). Microservices, event-driven, ML-assisted. Built from `University_ERP_Capstone_Documentation.md` (root), with the architecture upgraded for production scale.

**Authoritative docs (read these first in the new session):**
- Spec: `docs/superpowers/specs/2026-07-03-su-erp-multitenant-design.md`
- Plan (task-by-task, TDD): `docs/superpowers/plans/2026-07-03-su-erp-multitenant.md`
- Progress ledger: `.superpowers/sdd/progress.md` (git-ignored; the source of truth for what's done)

## 2. Locked decisions (do not re-litigate)

- **Frontend:** Next.js (App Router) + Tailwind — talks only to the gateway.
- **Backend:** Django 5 + DRF per business service; **FastAPI** for `ai-service`.
- **Multi-tenancy:** shared-DB, shared-schema, row-level `tenant_id`. Enforced by `suerp_common` `TenantModel`/`TenantManager` + `TenantMiddleware`.
- **Identity:** zero-trust — every service verifies the JWT signature itself (HS256, shared `JWT_SIGNING_KEY`), reads `sub`/`role`/`tenant` from claims, never trusts gateway headers.
- **Events:** RabbitMQ topic exchange `suerp.events`, routing key = event type. Transactional outbox (`suerp_common.outbox.publish_event` inside the caller's `transaction.atomic()`, drained by a Celery-beat `drain_outbox_task`) + idempotent consumers (`@idempotent` from `suerp_common.inbox`, dedupe by `event_id`).
- **Consumers run outside request context** → resolve tenant from `event["tenant_id"]` and use `Model.all_objects` with explicit `tenant_id` (NOT `.objects`, which returns an UNFILTERED cross-tenant queryset when no context is set).
- **Gateway:** lightweight Nginx (not Kong).
- **Config:** `django-environ` + `dj-database-url`; `DATABASE_URL`/`REDIS_URL`/`RABBITMQ_URL`/`JWT_SIGNING_KEY` from env with local-Docker fallback (sqlite when `DATABASE_URL` absent).
- **Response envelope:** `{success, data, message, errors}` everywhere (`suerp_common.envelope.ok/fail` + exception_handler). Pagination default 20 / max 100. URLs `/api/v1/...`.

## 3. User preferences (must follow)

- **Commits:** author as `Divanshu0212 <divanshu0212@gmail.com>` ONLY. No `Co-Authored-By: Claude` trailer. (repo git config already set to this.)
- **Commit cadence:** commit after every successful subphase/task.
- **No useless docs:** don't generate verbose superpowers report files; terse implementer/reviewer contracts (status + commits + one-line test summary + concerns). No extra README/design docs unless the plan requires them as a deliverable.
- **Subagent model:** use **Opus 4.8** (`claude-opus-4-8`) for IMPLEMENTER subagents. Reviewers can use a mid-tier model (sonnet).
- **Don't reconfirm from docs mid-build** — keep implementing; fold summaries in at the end.

## 4. Toolchain / environment

- Python 3.12 via **uv**: venv at `/home/divanshub/Desktop/Capstone/.venv`, uv at `/home/divanshub/.local/bin/uv`.
- Install a service's deps: `cd services/<svc> && /home/divanshub/.local/bin/uv pip install --python ../../.venv -r requirements.txt`. `suerp_common` is installed editable already.
- Run tests: `cd services/<svc> && ../../.venv/bin/pytest -q` (Django services) or from the service dir for ai-service.
- Lint from repo root: `.venv/bin/ruff check services --fix && .venv/bin/black services -q && .venv/bin/isort services -q`. (ruff does NOT sort imports — isort owns that; migrations excluded from ruff. Config in root `pyproject.toml`.)
- Infra: `infra/docker-compose.yml` (Postgres+PgBouncer+Redis+RabbitMQ+Prometheus+Grafana). `infra/postgres/init-multi-db.sh` creates all 13 service DBs.
- Working branch: **`phase-1-foundation`** (NOT main). Current HEAD: `e8181ad`.

## 5. What's DONE (all reviewed & committed, ~143 tests passing)

| Component | Tests | Notes |
|---|---|---|
| `shared/libs/suerp_common` | 21 | tenancy, zero-trust JWT, envelope, outbox, idempotent inbox, events (pika) |
| infra docker-compose | — | 13 DBs, PgBouncer transaction pooling |
| `auth-service` | 23 | Institution(tenant)/User/LoginAudit, register/login/refresh/me, tenant-scoped JWT, lockout, `user.registered` outbox |
| `finance-service` | 14 | FeeStructure/Invoice/Payment/Receipt, simulated gateway, pay (idempotent, select_for_update), payment.success/failed outbox, consumes hostel.allocation.requested → invoice.created |
| `hostel-service` | 20 | Block/Room/Allocation..., allocate (saga start), **saga close**: order-independent PaymentOutcome reconciliation, confirm/release on finance events, timeout compensation that never releases a paid seat |
| `notification-service` | 10 | per-user inbox (JWT sub scoped), terminal fan-out consumer (payment.success/allocation.confirmed/grievance.scored) |
| `transport-service` | 17 | routes/seats/bookings, race-safe seat booking (partial unique + lock), tenant-namespaced Redis cache, pass activation on payment.success |
| `grievance-service` | 17 | Ticket/TicketComment, create → grievance.created (payload has raised_by), scored consumer auto-escalates high/critical |
| `ai-service` (FastAPI) | 7 | VADER+keyword sentiment/urgency, `grievance.created`→`grievance.scored` producer (wire-format EXACT match to suerp_common verified), TF-IDF chatbot intent routing |
| 7 stub services | 14 | student/attendance/exam/library/canteen/placement/analytics — prototype CRUD, tenant-isolated |

**The two demo centerpieces both work end-to-end and are tested:**
1. **Saga:** allocate → invoice → pay → confirm → notification in student inbox (hostel↔finance↔notification). Two Critical distributed-systems bugs (tenant-isolation-in-middleware; saga event-ordering/timeout race) were caught by the review loop and fixed.
2. **ML escalation:** grievance created → ai-service scores (VADER+keywords) → grievance.scored → grievance auto-escalates + notification to student.

## 6. What's REMAINING (do these, in order)

Follow the plan file's Phase 9–11 tasks. Use subagent-driven-development (implementer on Opus 4.8, reviewer on sonnet, review each task, commit after each).

**Phase 9 — Gateway (`gateway/`):** Nginx reverse proxy. Route `/api/v1/auth/*`→auth-service, `/api/v1/finance/*`→finance, `/hostel/*`, `/transport/*`, `/grievance/*`, `/notify/*`, `/ai/*`, and the 7 stub endpoints (students/attendance/exams/books/menu-items/drives/metrics) to their services. Add per-IP `limit_req` zones (stricter on `/auth/login`), gzip, pass `Authorization` through unchanged, add `X-Request-Id`. Add the `gateway` service + all backend services to `infra/docker-compose.yml` (they aren't in compose yet — only the data stack is). Verify routing with the stack up (or at minimum `nginx -t` config validation + a documented curl path).

**Phase 10 — Frontend (`frontend/su-erp-web/`):** Next.js App Router + Tailwind. `lib/api.ts` (fetch wrapper: gateway base URL from env, attaches bearer token, unwraps `{success,data}` envelope, throws on `success:false`). `lib/auth.ts` (token store, decode role+tenant). Login page → role dashboards (student: fees/pay [drives the saga], transport booking, raise grievance, inbox; warden: pending allocations, escalated grievances; admin: cross-service counts). A page that visibly shows allocation pending→confirmed after paying, and grievance urgency after ML scoring. Component/RTL tests where practical; `npm run build` must pass. Commit per dashboard.

**Phase 11 — CI, observability, docs:**
- `.github/workflows/ci.yml`: matrix over services → ruff/black/isort → pytest (coverage ≥70%) → bandit/pip-audit → docker build. Ephemeral Postgres/Redis service containers.
- Prometheus/Grafana: each Django service already has django-prometheus; wire `infra/prometheus/prometheus.yml` to scrape all services + a Grafana dashboard JSON.
- Root `README.md`: architecture, how to run the stack, how to demo the saga + ML escalation. Per-service `.env.example` (most exist). `shared/event-schemas/*.json` (JSON Schema per event type).

**FINAL DELIVERABLE the user explicitly asked for:** After Phases 9–11, write a markdown doc (e.g. `docs/REMAINING_MODULES.md`) that compares the original `University_ERP_Capstone_Documentation.md` module/feature catalogue against what's actually implemented, listing: which modules are fully built, which are stubbed (prototype), and which ML/feature items from the original doc remain designed-but-not-built (e.g. resume–JD matching 12.3, attendance dropout risk 12.5, room allocation optimizer 12.6, bus demand forecasting 12.7, payment anomaly 12.8, exam timetable CSP 12.9, book recommendation 12.10, plagiarism 12.11, admission/exam/library/canteen/placement/alumni/faculty full features, analytics CQRS dashboards). Be honest and specific.

## 7. Deferred findings (from review loops — address in a final hardening pass or note in README)

- Fail-open dev defaults: `JWT_SIGNING_KEY`/`SECRET_KEY`/`DEBUG` default to insecure dev values silently — require env or fail loud when `DEBUG=False`.
- `request.user.id` (JWT `sub`) cast into a `UUIDField` would 500 on a non-UUID sub — validate. (Template-wide, all services.)
- finance: add `UniqueConstraint(invoice, idempotency_key)` as DB-level defense-in-depth (currently row-lock only).
- hostel: never-invoiced allocations hold a bed forever (fail-safe tradeoff) — add a long-window/never-invoiced release policy.
- register (auth): catch IntegrityError → 400 (TOCTOU); consider refresh-token blacklist app.
- infra: pin `edoburu/pgbouncer` by digest; harden RabbitMQ creds before any non-local exposure.
- ai-service: `/ai/sentiment` + `/ai/chatbot/query` are unauthenticated (documented) — add HS256 verification before external exposure.

## 8. SDD mechanics (how this build has been run)

Subagent-driven: for each task — `bash <superpowers>/skills/subagent-driven-development/scripts/task-brief <plan> N` to extract a brief; dispatch an implementer (Opus 4.8) with the brief + exact interfaces/contracts + a terse report contract; on DONE run `scripts/review-package BASE HEAD` and dispatch a reviewer (sonnet) with the diff path; fix loop for Critical/Important; commit; append a line to `.superpowers/sdd/progress.md`. The superpowers scripts dir: `/home/divanshub/.claude/plugins/cache/claude-plugins-official/superpowers/6.1.0/skills/subagent-driven-development/scripts/`.

---



