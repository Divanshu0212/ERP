# Smart University Enterprise Resource Planning (SU-ERP) System
### Software Requirements & Architecture Documentation
**Version:** 1.0 | **Type:** Capstone Project | **Stack:** Django, Microservices, ML/NLP, DevOps

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Goals & Objectives](#2-goals--objectives)
3. [System Modules Overview](#3-system-modules-overview)
4. [High-Level Architecture](#4-high-level-architecture)
5. [Technology Stack](#5-technology-stack)
6. [Microservices — Detailed Design](#6-microservices--detailed-design)
7. [Database Design](#7-database-design)
8. [Inter-Service Communication](#8-inter-service-communication)
9. [Authentication & Authorization](#9-authentication--authorization)
10. [Security Architecture](#10-security-architecture)
11. [Performance & Optimization](#11-performance--optimization)
12. [ML & NLP Integration](#12-ml--nlp-integration)
13. [DevOps Practices (Pre-Deployment Scope)](#13-devops-practices-pre-deployment-scope)
14. [Testing Strategy](#14-testing-strategy)
15. [Repository & Folder Structure](#15-repository--folder-structure)
16. [API Design & Documentation Standards](#16-api-design--documentation-standards)
17. [Sample Data Models (Code-Level)](#17-sample-data-models-code-level)
18. [Development Roadmap](#18-development-roadmap)
19. [Capstone Presentation Angle](#19-capstone-presentation-angle)
20. [Appendix](#20-appendix)

---

## 1. Executive Summary

**SU-ERP** is a microservices-based enterprise system designed to digitize and automate the core administrative, academic, and campus-life operations of a university/college. Unlike a single monolithic Django app, SU-ERP is decomposed into independently deployable Django services, each owning its own database schema, communicating through REST APIs and an asynchronous message broker, and fronted by a single API Gateway.

The system distinguishes itself as a capstone project through three pillars:

1. **Microservices Engineering** — realistic service boundaries, independent data ownership, event-driven communication, and API Gateway pattern.
2. **Applied ML/NLP** — not bolted on, but embedded into real workflows: a campus support chatbot, complaint sentiment triage, attendance/dropout risk prediction, resume-job matching, timetable optimization, and bus demand forecasting.
3. **Security & Performance Engineering** — OWASP-aligned hardening, caching, async task processing, and observability, all built with **free-tier cloud resources** (Neon/Supabase Postgres, Upstash Redis, CloudAMQP, etc.) so the whole system can be built and demoed at zero cost.

---

## 2. Goals & Objectives

| # | Objective | Success Metric |
|---|-----------|-----------------|
| G1 | Digitize core university operations end-to-end | ≥10 functional modules |
| G2 | Demonstrate real microservices architecture | ≥6 independently deployable services + gateway |
| G3 | Embed ML/NLP meaningfully, not decoratively | ≥4 working ML/NLP features with measurable output |
| G4 | Harden the system against common attack vectors | Pass OWASP ZAP baseline scan with no High findings |
| G5 | Demonstrate DevOps maturity (excluding deployment) | CI pipeline, containerized services, automated tests, code quality gates |
| G6 | Keep infra cost at $0 during development | Use free tiers only (Neon/Supabase, Upstash, CloudAMQP, GitHub Actions) |

---

## 3. System Modules Overview

Each module below maps to a bounded context and, in most cases, its own microservice.

| Module | Core Function | Owning Service |
|---|---|---|
| **Identity & Access** | Registration, login, roles (Student/Faculty/Admin/Warden/Driver), SSO-style token issuance | `auth-service` |
| **Student Information System (SIS)** | Student profiles, enrollment, academic records, document uploads | `student-service` |
| **Admission Management** | Online application, document verification, merit list generation, seat allotment | `admission-service` |
| **Attendance Management** | Class-wise attendance, biometric/QR check-in hooks, defaulter alerts | `attendance-service` |
| **Examination & Result Management** | Exam scheduling, hall tickets, marks entry, grade computation (GPA/CGPA), result publishing | `exam-service` |
| **Fee & Payment Management** | Fee structure, invoices, online payment gateway integration (test mode), receipts, defaulters | `finance-service` |
| **Hostel Management** | Room inventory, allocation, mess menu, leave requests, visitor logs, maintenance complaints | `hostel-service` |
| **Bus/Transport Ticket Booking** | Routes, stops, schedules, seat booking, live-seat-count, pass generation, driver dashboard | `transport-service` |
| **Library Management** | Catalogue, issue/return, fines, reservation queue, e-book links | `library-service` |
| **Cafeteria/Canteen Management** | Digital menu, pre-ordering, token/queue system, wallet-based payment | `canteen-service` |
| **Complaint & Grievance Redressal** | Ticket-style complaints (hostel/academic/ragging/IT), auto-routing, sentiment-based escalation | `grievance-service` |
| **Notice Board & Announcements** | Role/department-targeted notices, push/email notifications | `notification-service` |
| **Placement & Career Cell** | Company drives, resume upload, JD-resume matching, interview scheduling | `placement-service` |
| **Faculty Management** | Faculty profiles, course allocation, leave management, workload tracking | `faculty-service` |
| **Alumni Network** | Alumni directory, event announcements, mentorship requests | `alumni-service` |
| **AI Campus Assistant (Chatbot)** | NLP-based FAQ/query resolution across all modules (fees, timetable, library, bus) | `ai-service` |
| **Analytics & Reporting Dashboard** | Cross-service aggregated dashboards for admin (attendance trends, revenue, occupancy) | `analytics-service` (reads via events, not direct DB access) |

> **Capstone tip:** You don't need to build all 17 modules with full depth. Pick 4–5 "hero modules" (e.g., Hostel, Transport, Attendance, Placement, Grievance) to implement with full CRUD + ML, and stub the rest with basic CRUD. This is explicitly planned for in the [Roadmap](#18-development-roadmap).

---

## 4. High-Level Architecture

```
                                   ┌─────────────────────────┐
                                   │   React/Next.js Client   │  (or Django templates)
                                   │  Web + Mobile (PWA)      │
                                   └────────────┬─────────────┘
                                                │ HTTPS (JWT)
                                   ┌────────────▼─────────────┐
                                   │      API GATEWAY          │
                                   │  (Kong / Django + Nginx / │
                                   │   Traefik) — routing,     │
                                   │  rate-limit, auth check,  │
                                   │  request logging          │
                                   └──────┬─────────┬──────────┘
             ┌───────────────┬───────────┼─────────┼───────────┬────────────────┐
             │               │           │         │           │                │
     ┌───────▼─────┐ ┌───────▼─────┐┌────▼───┐┌────▼─────┐┌────▼──────┐  ┌──────▼──────┐
     │auth-service │ │student-svc  ││hostel- ││transport-││finance-   │  │ ...more     │
     │  (Postgres) │ │ (Postgres)  ││service ││service   ││service    │  │ services    │
     └───────┬─────┘ └───────┬─────┘└───┬────┘└────┬─────┘└─────┬─────┘  └──────┬──────┘
             │               │          │          │            │               │
             └───────────────┴────┬─────┴──────────┴────────────┴───────────────┘
                                   │
                       ┌───────────▼────────────┐
                       │  Message Broker (RabbitMQ /│
                       │  Redis Streams — async     │
                       │  events: fee.paid,          │
                       │  complaint.created,         │
                       │  attendance.low, etc.)      │
                       └───────────┬────────────┘
                                   │
                     ┌─────────────┴──────────────┐
                     │                             │
             ┌───────▼────────┐          ┌─────────▼─────────┐
             │  ai-service      │          │ notification-svc  │
             │ (NLP/ML models,  │          │ (email/SMS/push)  │
             │  FastAPI or DRF) │          └────────────────────┘
             └──────────────────┘

  Shared infra: Redis (cache + Celery broker/result backend), Elasticsearch (optional,
  search/logs), Prometheus + Grafana (metrics), ELK/Loki (logs) — all local/free-tier.
```

### Architectural Style
- **Pattern:** Microservices with Database-per-Service, API Gateway, and Event-Driven choreography for cross-service side effects (e.g., fee payment → notification; complaint created → sentiment analysis → priority routing).
- **Synchronous calls** (REST, via gateway) used only for direct user-facing reads/writes.
- **Asynchronous events** (message broker) used for anything that isn't part of the immediate request/response cycle — this is what makes it a *real* microservices system instead of a "distributed monolith."

---

## 5. Technology Stack

| Layer | Technology | Notes |
|---|---|---|
| **Backend Framework** | Django 5.x + Django REST Framework | One Django project per microservice |
| **API Gateway** | Kong Gateway (OSS) *or* Django-based lightweight gateway with `django-ninja` | Kong preferred for real DevOps optics |
| **Databases** | PostgreSQL (Neon.tech or Supabase free tier) | Neon: 100 CU-hrs/mo compute, scale-to-zero, 0.5GB/branch. Supabase: 500MB DB + built-in Auth/Storage. Use **Neon** for pure DB-per-service isolation via branching (1 project → multiple branches = free per-service DBs); use **Supabase** if you also want free file storage. |
| **Cache** | Redis (Upstash free tier — 10k commands/day, or local Redis in Docker for dev) | Session cache, query cache, Celery broker |
| **Message Broker** | RabbitMQ (CloudAMQP free "Little Lemur" plan) or Redis Streams | Async event bus |
| **Async Tasks** | Celery + Celery Beat | OTP emails, report generation, ML inference jobs |
| **Search** | PostgreSQL full-text search (free) or Elasticsearch (self-hosted in Docker for dev) | Library catalogue, notice search |
| **ML/NLP Libraries** | scikit-learn, spaCy, HuggingFace Transformers (DistilBERT/MiniLM), sentence-transformers, Prophet/statsmodels | Detailed in Section 12 |
| **Auth** | `djangorestframework-simplejwt`, OAuth2 (`django-oauth-toolkit`) for third-party/alumni SSO | JWT access + refresh tokens |
| **Containerization** | Docker + Docker Compose (local orchestration only, no deployment yet) | Each service = 1 Dockerfile |
| **CI** | GitHub Actions | Lint → Test → Build image → (stop before deploy) |
| **API Docs** | drf-spectacular (OpenAPI 3) + Swagger UI / Redoc | Auto-generated per service |
| **Monitoring (local)** | Prometheus + Grafana, `django-prometheus` | Optional but strong capstone differentiator |
| **Frontend** | React (Vite) or Next.js, Tailwind CSS | Talks only to API Gateway |
| **Version Control** | Git, monorepo with per-service folders (see Section 15) | |

---

## 6. Microservices — Detailed Design

For each service: **Responsibility**, **Key Endpoints**, **Owned Data**, **Events Published/Consumed**.

### 6.1 `auth-service`
- **Responsibility:** User registration, login, JWT issuance/refresh, RBAC (roles: Student, Faculty, Warden, Driver, Admin, Alumni), password reset, MFA (optional TOTP).
- **Key Endpoints:** `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`, `POST /auth/mfa/verify`
- **Owned Data:** `User`, `Role`, `Permission`, `RefreshToken`, `LoginAudit`
- **Publishes:** `user.registered`, `user.login_failed_x5` (for security alerting)
- **Consumes:** none

### 6.2 `student-service`
- **Responsibility:** Academic profile, enrollment, semester records, document vault reference.
- **Key Endpoints:** `GET/POST /students`, `GET /students/{id}/academic-history`, `POST /students/{id}/documents`
- **Owned Data:** `StudentProfile`, `Enrollment`, `Document`
- **Publishes:** `student.enrolled`
- **Consumes:** `user.registered` (auto-create shell profile)

### 6.3 `hostel-service`
- **Responsibility:** Block/room inventory, room allocation algorithm, mess menu, leave-in/leave-out requests, visitor log, room-maintenance complaints.
- **Key Endpoints:** `GET /hostel/rooms/available`, `POST /hostel/allocate`, `POST /hostel/leave-request`, `GET /hostel/mess-menu`, `POST /hostel/complaints`
- **Owned Data:** `Block`, `Room`, `Allocation`, `LeaveRequest`, `VisitorLog`, `MessMenu`
- **Publishes:** `hostel.allocated`, `hostel.complaint.created`
- **Consumes:** `student.enrolled`
- **ML hook:** Room allocation optimizer (constraint-based; groups by course/preferences) — see 12.6

### 6.4 `transport-service`
- **Responsibility:** Routes/stops master data, bus schedules, seat booking, e-pass QR generation, driver live-trip dashboard.
- **Key Endpoints:** `GET /transport/routes`, `GET /transport/routes/{id}/seats`, `POST /transport/bookings`, `GET /transport/pass/{student_id}`, `POST /transport/driver/trip/start`
- **Owned Data:** `Route`, `Stop`, `BusSchedule`, `Seat`, `Booking`, `Pass`
- **Publishes:** `transport.booked`, `transport.pass.issued`
- **Consumes:** `finance.payment.success` (confirm seasonal pass after payment)
- **ML hook:** Route-wise demand forecasting to suggest schedule changes — see 12.7

### 6.5 `finance-service`
- **Responsibility:** Fee heads/structures, invoice generation, payment gateway integration (Razorpay/Stripe test mode), receipts, defaulter tracking.
- **Key Endpoints:** `GET /finance/invoices`, `POST /finance/pay`, `GET /finance/receipts/{id}`, `GET /finance/defaulters`
- **Owned Data:** `FeeStructure`, `Invoice`, `Payment`, `Receipt`
- **Publishes:** `finance.payment.success`, `finance.payment.failed`, `finance.defaulter.flagged`
- **Consumes:** `student.enrolled` (auto-generate first invoice)
- **ML hook:** Payment-fraud/anomaly detection (unusual amount/time patterns) — see 12.8

### 6.6 `attendance-service`
- **Responsibility:** Daily attendance capture (manual/QR/biometric-webhook), defaulter computation, attendance certificates.
- **Key Endpoints:** `POST /attendance/mark`, `GET /attendance/student/{id}/summary`, `GET /attendance/course/{id}/report`
- **Owned Data:** `AttendanceRecord`, `AttendanceSummary`
- **Publishes:** `attendance.low_flagged`
- **ML hook:** Dropout-risk / low-attendance prediction — see 12.5

### 6.7 `exam-service`
- **Responsibility:** Exam timetable, hall ticket generation, marks entry, grade/CGPA computation, result publishing.
- **Key Endpoints:** `POST /exam/schedule`, `GET /exam/hall-ticket/{student_id}`, `POST /exam/marks`, `GET /exam/results/{student_id}`
- **Owned Data:** `ExamSchedule`, `HallTicket`, `Marksheet`, `Grade`
- **Publishes:** `exam.result.published`
- **ML hook:** Auto-generated conflict-free exam timetable (constraint satisfaction) — see 12.9

### 6.8 `library-service`
- **Responsibility:** Catalogue CRUD, issue/return, fine calculation, reservation queue.
- **Key Endpoints:** `GET /library/search`, `POST /library/issue`, `POST /library/return`, `POST /library/reserve`
- **Owned Data:** `Book`, `Copy`, `IssueRecord`, `Reservation`
- **Publishes:** `library.overdue.flagged`
- **ML hook:** Book recommendation engine (collaborative filtering) — see 12.10

### 6.9 `canteen-service`
- **Responsibility:** Digital menu, pre-orders, token queue, campus-wallet debit.
- **Key Endpoints:** `GET /canteen/menu`, `POST /canteen/order`, `GET /canteen/order/{id}/status`
- **Owned Data:** `MenuItem`, `Order`, `WalletTransaction`

### 6.10 `grievance-service`
- **Responsibility:** Ticketing for complaints (hostel, academic, harassment, IT), status tracking, escalation.
- **Key Endpoints:** `POST /grievance`, `GET /grievance/{id}`, `PATCH /grievance/{id}/status`
- **Owned Data:** `Ticket`, `TicketComment`, `EscalationLog`
- **Publishes:** `grievance.created`
- **Consumes:** feeds into `ai-service` for sentiment scoring; result written back via callback/event
- **ML hook:** Sentiment analysis + urgency classification — see 12.2

### 6.11 `notification-service`
- **Responsibility:** Central fan-out for email/SMS/push/in-app notices, templated messages.
- **Key Endpoints:** `POST /notify/broadcast`, `GET /notify/inbox/{user_id}`
- **Owned Data:** `Notification`, `NoticeTemplate`
- **Consumes:** almost every `*.created` / `*.flagged` event from other services

### 6.12 `placement-service`
- **Responsibility:** Company drives, JD postings, resume upload, shortlist generation, interview scheduling.
- **Key Endpoints:** `POST /placement/drives`, `POST /placement/apply`, `GET /placement/{drive_id}/matches`
- **Owned Data:** `Drive`, `JobDescription`, `Application`, `ResumeProfile`
- **ML hook:** Resume–JD semantic matching using sentence embeddings — see 12.3

### 6.13 `ai-service`
- **Responsibility:** Central NLP/ML inference microservice (kept separate from business services so models can scale/be swapped independently). Exposes internal-only endpoints consumed by other services and a public chatbot endpoint via gateway.
- **Key Endpoints:** `POST /ai/chatbot/query`, `POST /ai/sentiment`, `POST /ai/resume-match`, `POST /ai/attendance-risk`, `POST /ai/plagiarism-check`
- **Tech:** Can be Django+DRF (consistency) or FastAPI (better async/ML serving) — documented tradeoff in 12.1.
- **Owned Data:** Model artifacts (not user data) — stateless inference service, reads features via API calls to other services or receives them in the request payload.

### 6.14 `analytics-service` (optional stretch)
- **Responsibility:** Consumes events from the broker to build read-optimized aggregate tables for admin dashboards (CQRS-lite pattern) — e.g., daily attendance %, revenue collected, hostel occupancy %, bus utilization.
- **Owned Data:** Denormalized aggregate tables only.

---

## 7. Database Design

### 7.1 Database-per-Service on Free Tiers
Since a single free Postgres instance is limited (Neon: 0.5GB/branch, Supabase: 500MB total), use this practical strategy:

| Strategy | How |
|---|---|
| **Neon branching** | One Neon **project** → create a **branch per microservice** (`auth-db`, `hostel-db`, `transport-db`, ...). Each branch is a logically isolated Postgres database with its own connection string, satisfying "database-per-service" without needing 10 separate paid accounts. Free tier gives 10 branches. |
| **Supabase as secondary** | Use Supabase's free project for services needing file storage (e.g., `student-service` documents, `placement-service` resumes) since it bundles 1GB object storage + Postgres. |
| **SQLite for local dev** | Each service's `settings.py` uses SQLite in `DEBUG` mode and swaps to Neon/Supabase Postgres via `DATABASE_URL` env var in staging — via `dj-database-url`. |
| **Redis (Upstash free)** | Shared across services for caching + Celery, NOT for primary data storage. |

> **Critical microservices rule:** No service is allowed to connect directly to another service's database branch. All cross-service data access happens via REST API or async events — this is what you'll be graded on if a professor inspects your architecture.

### 7.2 Core Schemas (per service, simplified ER overview)

**auth-service**
```
User(id, username, email, password_hash, role, is_active, created_at)
Role(id, name)              # Student, Faculty, Warden, Driver, Admin, Alumni
RefreshToken(id, user_id, token, expires_at, revoked)
LoginAudit(id, user_id, ip, success, timestamp)
```

**student-service**
```
StudentProfile(id, user_id[FK-ref-only], roll_no, department, batch, semester, cgpa)
Enrollment(id, student_id, course_id, semester, status)
Document(id, student_id, doc_type, file_url, verified)
```

**hostel-service**
```
Block(id, name, gender_type, warden_id)
Room(id, block_id, room_no, capacity, occupied_count)
Allocation(id, room_id, student_id, allocated_on, vacated_on)
LeaveRequest(id, student_id, from_date, to_date, reason, status)
VisitorLog(id, student_id, visitor_name, purpose, check_in, check_out)
MessMenu(id, block_id, day_of_week, meal_type, items)
```

**transport-service**
```
Route(id, name, start_point, end_point)
Stop(id, route_id, name, sequence, lat, lng)
BusSchedule(id, route_id, bus_no, driver_id, departure_time, capacity)
Booking(id, student_id, schedule_id, seat_no, booking_date, status)
Pass(id, student_id, route_id, valid_from, valid_to, qr_code)
```

**finance-service**
```
FeeStructure(id, department, semester, head, amount)
Invoice(id, student_id, fee_structure_id, due_date, amount, status)
Payment(id, invoice_id, gateway_ref, amount, method, status, paid_at)
Receipt(id, payment_id, receipt_no, pdf_url)
```

**attendance-service**
```
AttendanceRecord(id, student_id, course_id, date, status, marked_by)
AttendanceSummary(id, student_id, course_id, present_pct, semester)
```

**exam-service**
```
ExamSchedule(id, course_id, exam_date, room_no, duration)
HallTicket(id, student_id, exam_schedule_id, seat_no, qr_code)
Marksheet(id, student_id, course_id, internal, external, total, grade)
```

**library-service**
```
Book(id, isbn, title, author, category, total_copies)
Copy(id, book_id, copy_no, status)
IssueRecord(id, copy_id, student_id, issue_date, due_date, return_date, fine)
Reservation(id, book_id, student_id, queued_at, status)
```

**grievance-service**
```
Ticket(id, raised_by, category, description, sentiment_score, urgency, status, assigned_to)
TicketComment(id, ticket_id, comment_by, text, created_at)
```

**placement-service**
```
Drive(id, company_name, job_title, ctc, eligibility_criteria, drive_date)
ResumeProfile(id, student_id, resume_url, parsed_skills, embedding_vector)
Application(id, drive_id, student_id, match_score, status)
```

> Store `embedding_vector` as a JSON/array field or, for a stronger capstone story, use `pgvector` extension (supported on Neon and Supabase free tiers) for real vector similarity search.

---

## 8. Inter-Service Communication

### 8.1 Synchronous (REST via Gateway)
Used when the caller needs an immediate response (e.g., frontend fetching a student's hostel status). All synchronous calls pass through the **API Gateway**, which handles:
- Routing (`/api/v1/hostel/*` → `hostel-service`)
- JWT validation (verifies signature, injects `X-User-Id`, `X-User-Role` headers downstream)
- Rate limiting per-user/per-IP
- Request/response logging

### 8.2 Asynchronous (Event Bus)
Used for side effects that shouldn't block the main request. Recommended broker: **RabbitMQ (CloudAMQP free "Little Lemur" — 1M messages/month, 20 connections)**, using **topic exchanges**.

**Example event flow — Fee Payment:**
```
finance-service --publishes--> "finance.payment.success" {student_id, amount, invoice_id}
        │
        ├──> notification-service consumes → sends email/SMS receipt
        ├──> transport-service consumes → activates seasonal bus pass if applicable
        └──> analytics-service consumes → updates revenue dashboard aggregate
```

**Example event flow — Grievance Sentiment Routing:**
```
grievance-service --publishes--> "grievance.created" {ticket_id, text}
        │
        └──> ai-service consumes → runs sentiment + urgency model
                    │
                    └──publishes--> "grievance.scored" {ticket_id, sentiment, urgency}
                                        │
                                        └──> grievance-service consumes → updates ticket priority
                                        └──> notification-service consumes → alerts warden if urgent
```

### 8.3 Saga Pattern (for multi-service consistency)
For flows spanning 2+ services with financial/state implications (e.g., hostel allocation requiring a fee payment), implement a lightweight **choreography-based saga**:
1. `hostel.allocation.requested` → hostel-service reserves room (status=`pending`)
2. `finance.invoice.created` → finance-service generates hostel fee invoice
3. On `finance.payment.success` → hostel-service confirms allocation (status=`confirmed`)
4. On timeout/`finance.payment.failed` → hostel-service releases the room (compensating action)

This is a strong point to highlight in your capstone report/viva — it shows understanding of distributed transaction challenges, not just CRUD APIs.

---

## 9. Authentication & Authorization

- **Token type:** JWT (access token ~15 min TTL, refresh token ~7 days, rotated on use) via `djangorestframework-simplejwt`.
- **Central issuance:** Only `auth-service` issues tokens. All other services are **stateless resource servers** — they only *validate* JWTs (shared public key / HMAC secret via env var) and never touch the `User` table directly.
- **RBAC:** Role embedded in JWT claims (`role: student|faculty|warden|driver|admin|alumni`). Each service enforces its own permission classes (DRF `permissions.BasePermission` subclasses) based on the role claim — e.g., only `warden` role can approve hostel leave requests, only `driver` role can start a trip.
- **Object-level permissions:** Students can only access their *own* records (`request.user.id == obj.student_id`) — enforced via DRF's `has_object_permission`.
- **MFA (optional, strong capstone add-on):** TOTP-based 2FA for Admin/Warden roles using `django-otp`.
- **Inter-service auth:** Services calling each other internally (not via gateway) use short-lived **service tokens** (client-credentials OAuth2 flow via `django-oauth-toolkit`) so a compromised service can't impersonate a user.

---

## 10. Security Architecture

Map directly to OWASP Top 10 for the report/viva:

| Risk | Mitigation |
|---|---|
| **Broken Access Control** | RBAC + object-level permissions on every viewset; deny-by-default `IsAuthenticated` + custom permission classes |
| **Cryptographic Failures** | HTTPS everywhere (even in local dev via mkcert), passwords hashed with Argon2 (`django.contrib.auth.hashers.Argon2PasswordHasher`), secrets in `.env`/vault, never in code |
| **Injection** | Django ORM parameterized queries by default; explicit input validation via DRF serializers; no raw SQL without parameterization |
| **Insecure Design** | Threat-modeling each service boundary; rate-limited endpoints; saga compensations for financial flows |
| **Security Misconfiguration** | `DEBUG=False` in staging, `django-environ` for config, security headers via `django-secure` / `SecurityMiddleware` (HSTS, X-Frame-Options, X-Content-Type-Options) |
| **Vulnerable Components** | `pip-audit` / `safety` in CI pipeline to scan dependencies |
| **Identification/Auth Failures** | JWT short TTL + refresh rotation, account lockout after N failed logins (tracked via `LoginAudit`), MFA for privileged roles |
| **Software/Data Integrity Failures** | CI pipeline verifies commit signing (optional), Docker image checksums |
| **Logging & Monitoring Failures** | Centralized structured logging (JSON logs → Loki/ELK), audit trail for sensitive actions (fee refunds, grade changes) |
| **SSRF** | Whitelist outbound domains for any service making external calls (payment gateway, ML APIs) |

**Additional hardening:**
- **Rate limiting:** `django-ratelimit` or Gateway-level (Kong plugin) — e.g., 5 login attempts/min/IP.
- **CSRF:** Enabled for any session-based/browsable API views; JWT-based API calls are inherently CSRF-exempt but must strictly validate `Origin`/`Referer` for state-changing requests from browsers.
- **Input sanitization:** DRF serializers + `bleach` for any rich-text fields (notices, grievance descriptions) to prevent stored XSS.
- **File upload security:** Validate MIME type + extension + size on document/resume uploads; store outside web root; scan filenames for path traversal.
- **Secrets management:** `.env` (dev) → GitHub Actions secrets (CI) → (future) Vault/Doppler (deployment, out of current scope).
- **Audit logging:** Every grade change, fee waiver, or room reallocation logged with actor, timestamp, before/after state.

---

## 11. Performance & Optimization

| Technique | Where Applied |
|---|---|
| **Redis caching** | Cache expensive reads: bus seat availability, library catalogue search, dashboard aggregates (TTL 30–60s for near-real-time data) |
| **Database indexing** | Index FKs, `student_id`, `status`, `date` columns used in filters; composite indexes for common query patterns (e.g., `(course_id, date)` on AttendanceRecord) |
| **Query optimization** | `select_related`/`prefetch_related` to avoid N+1 queries; DRF pagination on all list endpoints (default page size 20) |
| **Async task offloading** | Celery for: PDF generation (receipts, hall tickets), bulk email/SMS, ML model inference for non-real-time tasks (e.g., nightly dropout-risk scoring) |
| **Connection pooling** | `pgbouncer`-style pooling (Supabase provides this built-in; for Neon use its pooled connection string) since free-tier DBs cap concurrent connections |
| **API Gateway caching** | Cache static/semi-static GET responses (routes, notices) at gateway level |
| **Database read-replicas (conceptual)** | Document as a future scaling step (Neon branch-as-read-replica) — good to mention in report even if not implemented |
| **Lazy loading / pagination on frontend** | Infinite scroll for notices, library search, complaint lists |
| **Compression** | Gzip/Brotli middleware for API responses |
| **N+1 event storm avoidance** | Batch event publishing where possible (e.g., bulk attendance marking publishes one summary event, not one per student) |

---

## 12. ML & NLP Integration

This is the section that will most differentiate your capstone. Each sub-section includes **purpose, technique, and why it's justified** (not just "AI for AI's sake").

### 12.1 AI Service Architecture Decision
Build `ai-service` as a **separate lightweight Django (DRF) or FastAPI microservice** that loads models once at startup and exposes inference endpoints. Recommendation: **FastAPI** for this one service specifically, since:
- Native async support suits I/O-bound model calls better.
- Pydantic validation is a natural fit for ML I/O contracts.
- It's a good talking point in your viva: "I used Django for CRUD-heavy business services and FastAPI for the ML inference layer, chosen for its async performance profile" — shows deliberate, justified technology selection rather than one-size-fits-all.

(If you prefer stack consistency for grading rubrics that require "pure Django microservices," DRF works fine too — just note the tradeoff in your report.)

### 12.2 Complaint Sentiment & Urgency Classification (`grievance-service` ↔ `ai-service`)
- **Technique:** Fine-tune / use a pretrained DistilBERT (`distilbert-base-uncased-finetuned-sst-2-english`) or a lighter `TextBlob`/`VADER` model for sentiment polarity; combine with a keyword/urgency classifier (rule-based + Logistic Regression on TF-IDF features) trained on labeled sample grievances (ragging, harassment, safety → auto-critical).
- **Output:** `sentiment_score (-1 to 1)`, `urgency (low/medium/high/critical)`.
- **Business value:** Auto-escalates safety-critical complaints to wardens instantly instead of waiting in a FIFO queue.

### 12.3 Resume–Job Description Matching (`placement-service` ↔ `ai-service`)
- **Technique:** `sentence-transformers` (e.g., `all-MiniLM-L6-v2`) to embed both resume text (parsed via `pdfplumber`/`docling`) and job description into vectors; compute cosine similarity; rank candidates.
- **Storage:** `pgvector` extension on Neon/Supabase for similarity search at scale (`ORDER BY embedding <=> query_embedding LIMIT 20`).
- **Output:** `match_score (0–100)` per student per drive, auto-shortlist top N.

### 12.4 AI Campus Assistant / Chatbot (`ai-service`, gateway-exposed)
- **Technique:** Intent classification (small transformer or even scikit-learn SVM on TF-IDF for a constrained FAQ domain) + slot extraction (spaCy NER for dates/course codes/roll numbers) + retrieval-augmented responses (semantic search over a curated FAQ/knowledge base using the same embedding model as 12.3).
- **Scope:** "When is my next bus?", "What's my library fine?", "What's the hostel mess menu today?" — answered by calling the relevant service's API with the extracted entities, not by hallucinating.
- **Why this is strong for a capstone:** It's a genuine multi-service orchestration — chatbot intent → API call to `transport-service`/`library-service`/`hostel-service` → NLG template response. Demonstrates NLP + microservices integration together.

### 12.5 Attendance-Based Dropout/At-Risk Prediction (`attendance-service` ↔ `ai-service`)
- **Technique:** Logistic Regression / Random Forest classifier on features: attendance %, trend (declining vs stable), historical grade performance (from `exam-service`), fee payment delays (from `finance-service`).
- **Output:** Weekly risk score per student; feeds into `notification-service` to alert academic advisors.
- **Data note:** Since this needs historical data, seed with a synthetic dataset (document this clearly as "simulated data for demonstration" in your report — completely acceptable for a capstone).

### 12.6 Hostel Room Allocation Optimizer (`hostel-service`)
- **Technique:** Constraint-satisfaction / greedy bipartite matching considering: department clustering preference, year-of-study grouping, special needs flags, room capacity. Can use `OR-Tools` (Google's CP-SAT solver) for an optimal assignment, or a simpler greedy heuristic for MVP.
- **Output:** Auto-suggested allocation list for warden approval (human-in-the-loop, not fully automated — good practice to mention).

### 12.7 Bus Demand Forecasting (`transport-service`)
- **Technique:** Time-series forecasting (Facebook Prophet or simple ARIMA/statsmodels) on historical booking counts per route/time-slot to recommend schedule adjustments (add/remove trips).
- **Output:** Weekly forecast dashboard for transport admin.

### 12.8 Payment Anomaly Detection (`finance-service`)
- **Technique:** Isolation Forest (scikit-learn) on payment features (amount deviation from expected fee, time-of-day, IP/device change) to flag potentially fraudulent or erroneous transactions for manual review.

### 12.9 Exam Timetable Auto-Generation (`exam-service`)
- **Technique:** Constraint satisfaction problem (CSP) using `OR-Tools` or `python-constraint` — no student has two exams at once, no room double-booked, faculty invigilation load balanced. This is classical AI (not ML), but a great addition to round out the "intelligent system" narrative.

### 12.10 Library Book Recommendation (`library-service`)
- **Technique:** Simple collaborative filtering (`surprise` library or matrix factorization) on issue-history data, or content-based fallback (TF-IDF on book descriptions/genres) for cold-start students.

### 12.11 Plagiarism/Similarity Check for Assignment Submissions (optional stretch, `exam-service`/`ai-service`)
- **Technique:** Sentence-embedding cosine similarity between submitted assignment text and a corpus of prior submissions/reference material. Flags similarity above threshold for faculty review.

> **Recommended MVP ML scope for a realistic timeline:** Implement 12.2 (sentiment), 12.3 (resume matching), 12.4 (chatbot), and 12.5 (attendance risk) fully. Document 12.6–12.11 as "designed but implemented at prototype/stub level" — this is honest, impressive, and manageable.

---

## 13. DevOps Practices (Pre-Deployment Scope)

Since deployment itself is explicitly out of scope for now, focus DevOps effort on **local orchestration, automation, and quality gates**:

### 13.1 Containerization
- One `Dockerfile` per service (multi-stage build: install deps → copy code → run via `gunicorn`).
- Root-level `docker-compose.yml` to spin up **all services + Postgres (local fallback) + Redis + RabbitMQ + gateway** together for local development/demo.
- Each service has its own `.env.example` documenting required variables.

### 13.2 CI Pipeline (GitHub Actions) — per service
```yaml
# .github/workflows/ci.yml (conceptual structure, one workflow per service or matrix build)
on: [push, pull_request]
jobs:
  lint:
    - flake8 / ruff
    - black --check
    - isort --check
  test:
    - pytest with coverage (pytest-django, pytest-cov)
    - coverage threshold gate (e.g., fail below 70%)
  security:
    - pip-audit / safety scan
    - bandit (static security analysis for Python)
  build:
    - docker build (validate Dockerfile, no push since deployment is out of scope)
```

### 13.3 Code Quality Gates
- Pre-commit hooks: `black`, `isort`, `flake8`, `detect-secrets` (prevents committing API keys/passwords).
- Branch protection: require CI pass + 1 review (even if solo, document the policy) before merge to `main`.

### 13.4 Observability (local)
- `django-prometheus` exposes `/metrics` per service → scraped by local Prometheus → visualized in Grafana (request latency, error rate, DB query count).
- Structured JSON logging (`python-json-logger`) → optionally shipped to local Loki/ELK via Docker Compose for a unified log search demo.
- This alone is a strong differentiator in a capstone demo — showing a live Grafana dashboard during your viva is memorable.

### 13.5 Infrastructure as Code (documentation-level)
- Even without deploying, write a `docker-compose.yml` + short Terraform/Ansible stub (even unexecuted) to show you *understand* IaC principles — mention in report as "prepared for future deployment phase."

### 13.6 Environment Strategy
| Env | Purpose | DB |
|---|---|---|
| `local` | Dev on laptop | SQLite or local Postgres container |
| `ci` | Automated testing | Ephemeral Postgres container (GitHub Actions service container) |
| `staging` (future) | Pre-prod demo | Neon/Supabase free-tier branch |

---

## 14. Testing Strategy

| Level | Tooling | Coverage Target |
|---|---|---|
| **Unit tests** | `pytest-django`, `factory_boy` for test fixtures | Model methods, serializer validation, permission classes |
| **Integration tests** | DRF `APIClient`, per-service test DB | Full endpoint request/response cycles |
| **Contract tests** | `pact-python` (optional, advanced) | Ensures gateway ↔ service API contracts don't break |
| **Event-driven tests** | Mock broker (`pytest` + `pika`/`celery` test mode) | Verify events are published/consumed correctly |
| **ML model tests** | Fixed test inputs → assert expected output ranges; regression tests to catch model drift | Sentiment classifier accuracy ≥ baseline threshold on holdout set |
| **Load testing (local)** | `locust` against docker-compose stack | Identify bottlenecks before "deployment phase" |
| **Security testing** | OWASP ZAP baseline scan against local stack | No High/Critical findings |

---

## 15. Repository & Folder Structure

**Recommended: Monorepo** (simpler for a solo/small-team capstone; still demonstrates service independence via folder + Docker boundaries).

```
su-erp/
├── gateway/                      # Kong config or lightweight Django gateway
│   └── docker-compose.gateway.yml
├── services/
│   ├── auth-service/
│   │   ├── manage.py
│   │   ├── auth_service/         # Django project
│   │   ├── accounts/             # Django app
│   │   ├── requirements.txt
│   │   ├── Dockerfile
│   │   └── .env.example
│   ├── student-service/
│   ├── hostel-service/
│   ├── transport-service/
│   ├── finance-service/
│   ├── attendance-service/
│   ├── exam-service/
│   ├── library-service/
│   ├── canteen-service/
│   ├── grievance-service/
│   ├── notification-service/
│   ├── placement-service/
│   ├── ai-service/                # FastAPI or DRF ML inference service
│   │   ├── main.py
│   │   ├── models/                # saved model artifacts (.pkl, .bin)
│   │   ├── inference/
│   │   └── Dockerfile
│   └── analytics-service/
├── shared/
│   ├── event-schemas/             # JSON Schemas for all published events
│   └── libs/                      # Shared Python package (e.g., common JWT validation middleware)
├── frontend/
│   └── su-erp-web/                # React/Next.js app
├── infra/
│   ├── docker-compose.yml         # Full local stack
│   ├── prometheus/
│   └── grafana/
├── .github/workflows/
├── docs/
│   ├── architecture-diagrams/
│   ├── api-specs/                 # OpenAPI YAML exports per service
│   └── er-diagrams/
└── README.md
```

---

## 16. API Design & Documentation Standards

- **Versioning:** URL-based, `/api/v1/...` per service.
- **Auto-generated OpenAPI:** `drf-spectacular` on every Django service → Swagger UI at `/api/schema/swagger-ui/`.
- **Consistent response envelope:**
```json
{
  "success": true,
  "data": { },
  "message": "Room allocated successfully",
  "errors": null
}
```
- **Consistent error format:**
```json
{
  "success": false,
  "data": null,
  "message": "Validation failed",
  "errors": {"room_id": ["This room is at full capacity."]}
}
```
- **Pagination:** Standard DRF `PageNumberPagination`, `page_size` default 20, max 100.
- **Naming convention:** Plural nouns, kebab-case for multi-word resources (`/leave-requests`, not `/leaveRequests`).

---

## 17. Sample Data Models (Code-Level)

Example for **`hostel-service`** (`hostel/models.py`):

```python
from django.db import models
import uuid

class Block(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=50)
    gender_type = models.CharField(max_length=10, choices=[("M", "Male"), ("F", "Female")])
    warden_id = models.UUIDField()  # reference only — no FK across services

class Room(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name="rooms")
    room_no = models.CharField(max_length=10)
    capacity = models.PositiveSmallIntegerField(default=2)
    occupied_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        indexes = [models.Index(fields=["block", "room_no"])]
        constraints = [
            models.UniqueConstraint(fields=["block", "room_no"], name="unique_room_per_block")
        ]

    @property
    def is_available(self):
        return self.occupied_count < self.capacity


class Allocation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="allocations")
    student_id = models.UUIDField()  # reference to student-service, no cross-DB FK
    allocated_on = models.DateField(auto_now_add=True)
    vacated_on = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=15,
        choices=[("pending", "Pending"), ("confirmed", "Confirmed"), ("vacated", "Vacated")],
        default="pending",
    )
```

Example serializer + permission-aware viewset (`hostel/views.py`):

```python
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Room, Allocation
from .serializers import RoomSerializer, AllocationSerializer
from .events import publish_event  # thin wrapper around pika/celery

class IsWardenOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return request.headers.get("X-User-Role") == "warden"

class RoomViewSet(viewsets.ModelViewSet):
    queryset = Room.objects.select_related("block").all()
    serializer_class = RoomSerializer
    permission_classes = [permissions.IsAuthenticated, IsWardenOrReadOnly]

    @action(detail=False, methods=["get"])
    def available(self, request):
        rooms = [r for r in self.get_queryset() if r.is_available]
        serializer = self.get_serializer(rooms, many=True)
        return Response({"success": True, "data": serializer.data, "message": "", "errors": None})

    @action(detail=True, methods=["post"])
    def allocate(self, request, pk=None):
        room = self.get_object()
        if not room.is_available:
            return Response(
                {"success": False, "data": None, "message": "Room full", "errors": {"room": ["at capacity"]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        allocation = Allocation.objects.create(
            room=room, student_id=request.data["student_id"], status="pending"
        )
        room.occupied_count += 1
        room.save(update_fields=["occupied_count"])
        publish_event("hostel.allocated", {
            "allocation_id": str(allocation.id),
            "student_id": str(allocation.student_id),
            "room_id": str(room.id),
        })
        return Response({"success": True, "data": AllocationSerializer(allocation).data,
                          "message": "Room allocated", "errors": None}, status=201)
```

---

## 18. Development Roadmap

Suggested **12–14 week capstone timeline**:

| Phase | Weeks | Deliverables |
|---|---|---|
| **Phase 0 — Planning** | 1 | Finalize scope, ER diagrams, architecture diagrams, set up repo + free-tier accounts (Neon/Supabase, Upstash, CloudAMQP) |
| **Phase 1 — Foundation** | 2–3 | `auth-service` full build, API Gateway routing skeleton, Docker Compose base stack, CI pipeline template |
| **Phase 2 — Core Hero Services** | 4–7 | `student-service`, `hostel-service`, `transport-service`, `finance-service` — full CRUD + auth integration + events |
| **Phase 3 — Secondary Services** | 8–9 | `attendance-service`, `exam-service`, `library-service`, `grievance-service`, `notification-service` |
| **Phase 4 — AI/ML Layer** | 9–11 | `ai-service`: sentiment (12.2), resume matching (12.3), chatbot (12.4), attendance risk (12.5) |
| **Phase 5 — Frontend Integration** | 10–12 | React/Next.js consuming gateway APIs, role-based dashboards |
| **Phase 6 — Security & Performance Hardening** | 12–13 | OWASP ZAP scan fixes, caching, rate limiting, load testing |
| **Phase 7 — Observability & Polish** | 13–14 | Prometheus/Grafana dashboards, final documentation, demo script, report writing |

---

## 19. Capstone Presentation Angle

When presenting/defending this project, structure your narrative around three "wow" pillars evaluators respond well to:

1. **"It's not a monolith pretending to be microservices"** — show the event bus live: trigger a fee payment in Postman, and show notification-service, transport-service, and analytics-service all reacting independently in logs/Grafana.
2. **"The AI is functional, not decorative"** — live-demo the chatbot answering "when's my next bus" by actually calling `transport-service`, and show a grievance auto-escalating due to sentiment analysis.
3. **"It's production-minded even without being deployed"** — show the CI pipeline green checkmarks, the security scan report, and the Grafana dashboard with real request metrics.

---

## 20. Appendix

### 20.1 Free-Tier Resource Summary (as of mid-2026)
| Service | Free Tier | Use |
|---|---|---|
| Neon (Postgres) | 100 CU-hrs/month, 10 branches, 0.5–3GB/branch, scale-to-zero | Per-service Postgres via branching |
| Supabase | 500MB DB, 1GB file storage, 50K MAU auth, 2 projects (pauses after 7 days idle) | File storage for documents/resumes; alt DB |
| Upstash Redis | ~10K commands/day free | Caching, Celery broker |
| CloudAMQP (RabbitMQ) | "Little Lemur" free plan, ~1M msgs/mo, 20 connections | Event bus |
| GitHub Actions | 2,000 free CI minutes/month (private repos) | CI/CD pipelines |
| HuggingFace models | Free to download/run locally (no inference API cost if self-hosted) | Sentiment, embeddings |

> Always re-verify current limits on each provider's pricing page before committing your architecture — free-tier terms change frequently.

### 20.2 Glossary
- **DB-per-Service:** Each microservice owns its schema exclusively; no other service queries it directly.
- **Saga Pattern:** A way to manage data consistency across services without distributed transactions, using a sequence of local transactions coordinated via events.
- **CQRS-lite:** Read-optimized aggregate views (here, `analytics-service`) built from write-side events, without full CQRS/event-sourcing complexity.

### 20.3 Suggested Diagrams to Produce Separately
- System Context Diagram (C4 Level 1)
- Container Diagram (C4 Level 2) — matches Section 4
- ER diagrams per service (Section 7)
- Sequence diagram: fee payment saga (Section 8.3)
- Sequence diagram: chatbot query → service orchestration (Section 12.4)

---

*End of Document — SU-ERP Software Documentation v1.0*
