# SU-ERP — Built vs. Designed: Module & Feature Coverage

Honest comparison of the original catalogue in `University_ERP_Capstone_Documentation.md`
against what the codebase actually implements as of branch `phase-1-foundation`.

**Legend**
- ✅ **Built** — real domain logic, tests, and (where applicable) events working end-to-end.
- 🟡 **Stub** — prototype: one tenant-isolated model + list/create endpoint + smoke test. No domain logic.
- ⬜ **Not built** — designed in the doc, absent in code.

> **Architecture note (beyond original spec):** the build adds **multi-tenancy**
> (shared-DB row-level `tenant_id`, `TenantModel`/`TenantManager`/`TenantMiddleware`),
> **zero-trust JWT** (every service verifies HS256 itself), a **transactional outbox +
> idempotent inbox**, and an **Nginx gateway** — none of which the original doc mandated.
> The original assumed DB-per-service on free tiers; this build keeps DB-per-service but
> layers tenancy on top for a multi-institution SaaS.

---

## 1. Services (doc §6)

| # | Service | Status | Built | Designed but missing |
|---|---------|--------|-------|----------------------|
| 6.1 | auth | ✅ Built | register, login, refresh, me; tenant-scoped JWT; role claim; login lockout (5×); `user.registered` outbox | logout, refresh-token blacklist, `Role`/`Permission` tables (RBAC is role-claim only), password reset, MFA/TOTP, `user.login_failed_x5` event |
| 6.2 | student | 🟡 Stub | tenant-isolated CRUD model + list/create | academic history, enrollment, document vault, `student.enrolled` event, consume `user.registered` |
| 6.3 | hostel | ✅ Built | Block/Room/Allocation/LeaveRequest/Complaint; `allocate` (saga start); saga close (confirm/release on finance events); timeout compensation that never releases a paid seat | VisitorLog, MessMenu + mess endpoints, allocation **optimizer** (current allocate is a naive first-available reserve), consume `student.enrolled` |
| 6.4 | transport | ✅ Built | routes/stops/schedules/bookings/Pass; race-safe seat booking (partial-unique + lock); tenant-namespaced Redis seat cache; pass activation on `finance.payment.success` | driver live-trip dashboard, QR e-pass generation, `transport.booked`/`pass.issued` events, demand forecasting |
| 6.5 | finance | ✅ Built | FeeStructure/Invoice/Payment/Receipt; `pay` (idempotent, `select_for_update`); **simulated** swappable gateway; `payment.success`/`failed` outbox; consumes `hostel.allocation.requested`→invoice | real Razorpay/Stripe test integration, defaulter tracking + `defaulter.flagged`, consume `student.enrolled` for first invoice, anomaly detection |
| 6.6 | attendance | 🟡 Stub | tenant-isolated CRUD model | mark/summary/report endpoints, defaulter compute, `attendance.low_flagged`, dropout-risk ML |
| 6.7 | exam | 🟡 Stub | tenant-isolated CRUD model | schedule/hall-ticket/marks/results, CGPA compute, `exam.result.published`, timetable CSP |
| 6.8 | library | 🟡 Stub | tenant-isolated CRUD model | search/issue/return/reserve, fine calc, `overdue.flagged`, recommendation engine |
| 6.9 | canteen | 🟡 Stub | tenant-isolated CRUD model | menu/order/token-queue, campus-wallet debit |
| 6.10 | grievance | ✅ Built | Ticket/TicketComment; `create`→`grievance.created` (payload carries `raised_by`); `grievance.scored` consumer auto-escalates high/critical to warden | `EscalationLog` model (escalation is a status flip), `PATCH /status` endpoint |
| 6.11 | notification | ✅ Built | per-user in-app inbox (JWT-`sub` scoped); mark-read; terminal fan-out consumer for `payment.success`/`allocation.confirmed`/`grievance.scored` | broadcast endpoint, templates, real email/SMS/push channels (in-app only) |
| 6.12 | placement | 🟡 Stub | tenant-isolated CRUD model | drives/apply/matches, resume upload, shortlisting, resume–JD ML |
| 6.13 | ai | ✅ Built (partial) | FastAPI; `/ai/sentiment` (VADER + keyword urgency); `/ai/chatbot/query` (TF-IDF intent routing); `grievance.created`→`grievance.scored` producer (wire-format verified) | `/ai/resume-match`, `/ai/attendance-risk`, `/ai/plagiarism-check` endpoints |
| 6.14 | analytics | 🟡 Stub | tenant-isolated CRUD model | CQRS-lite event-consuming aggregate tables (attendance %, revenue, occupancy, bus utilization) |

**Score:** 7 services fully built (auth, hostel, transport, finance, grievance, notification, ai),
7 stubbed (student, attendance, exam, library, canteen, placement, analytics).

---

## 2. ML / NLP items (doc §12)

| # | Item | Owner | Status | Notes |
|---|------|-------|--------|-------|
| 12.2 | Complaint sentiment & urgency | grievance ↔ ai | ✅ Built | VADER compound polarity + keyword urgency table (ragging/harassment→critical). Drives the auto-escalation demo end-to-end. |
| 12.3 | Resume–JD matching | placement ↔ ai | ⬜ Not built | No `/ai/resume-match`; placement is a stub. Designed as sentence-embedding similarity. |
| 12.4 | Campus chatbot | ai (gateway) | ✅ Built (simpler) | Implemented as TF-IDF + intent routing over a seed set, not the doc's broader assistant; returns templated answers, mocks downstream calls in tests. |
| 12.5 | Attendance dropout/at-risk | attendance ↔ ai | ⬜ Not built | No `/ai/attendance-risk`; attendance is a stub. |
| 12.6 | Hostel allocation optimizer | hostel | ⬜ Not built | `allocate` reserves the first available bed; no constraint-based grouping by course/preference. |
| 12.7 | Bus demand forecasting | transport | ⬜ Not built | No time-series/forecast; bookings are recorded but not modeled. |
| 12.8 | Payment anomaly detection | finance | ⬜ Not built | No anomaly scoring on amount/time patterns. |
| 12.9 | Exam timetable auto-generation | exam | ⬜ Not built | No CSP solver; exam is a stub. |
| 12.10 | Library book recommendation | library | ⬜ Not built | No collaborative filtering; library is a stub. |
| 12.11 | Plagiarism/similarity check | exam/ai | ⬜ Not built | No `/ai/plagiarism-check`. |

**Score:** 2 of 11 ML items built (12.2 fully, 12.4 in a simplified form). 9 remain designed-only.

---

## 3. Cross-cutting (doc §8–§14)

| Area | Status | Notes |
|------|--------|-------|
| Sync REST via gateway (§8.1) | ✅ Built | Nginx gateway, path routing, per-IP rate limits, `Authorization` passthrough, `X-Request-Id`. |
| Async event bus (§8.2) | ✅ Built | RabbitMQ topic exchange `suerp.events`, outbox + idempotent inbox. |
| Saga pattern (§8.3) | ✅ Built | Hostel allocation ↔ finance ↔ notification; order-independent correlation; timeout compensation. |
| AuthN/AuthZ (§9) | ✅ Built (core) | Zero-trust HS256 JWT, role claim, tenant claim. No MFA, no fine-grained `Permission` table. |
| Security (§10) | 🟡 Partial | Tenant isolation, JWT verification, lockout. Deferred: fail-loud secrets when `DEBUG=False`, RabbitMQ cred hardening, ai-service endpoint auth, UUID `sub` validation (see README "Known hardening TODOs"). |
| Performance (§11) | ✅ Built (core) | PgBouncer transaction pooling, Redis cache, read-DB alias, DB-level constraints for race safety. |
| CI (§13.2) | ✅ Built | GitHub Actions: lint + pytest/coverage matrix (14 services), bandit + pip-audit, docker build matrix, frontend build. |
| Observability (§13.4) | ✅ Built | django-prometheus `/metrics` on 13 services, Prometheus scrape config, Grafana dashboard (rate/latency/errors). Per-tenant metric labels not wired (stock middleware). |
| Containerization (§13.1) | ✅ Built | Per-service Dockerfiles + full-stack `docker-compose` (infra + all services + celery/consumers + frontend). |
| Testing (§14) | ✅ Built | ~143 backend tests + 19 frontend tests; cross-tenant isolation tested per model; saga + escalation integration tests. |
| Frontend | ✅ Built | Next.js App Router + Tailwind; login, role dashboards (student/warden/admin), saga + ML-escalation demo pages. |

---

## 4. Bottom line

**Demo-complete.** The two headline flows the capstone is pitched on — the **hostel↔finance
saga** and the **grievance ML auto-escalation** — both work end-to-end with tests, a gateway,
and a UI that visibly shows the state transitions.

**Breadth is intentionally partial.** 7 of 14 services are prototype stubs, and 9 of 11 ML
items are designed-only. The build prioritized **depth on the distributed-systems and ML story**
(saga correctness, zero-trust multi-tenancy, event choreography, one real NLP pipeline) over
CRUD breadth across every module. The stubs and remaining ML items are the natural roadmap for
continued work.
