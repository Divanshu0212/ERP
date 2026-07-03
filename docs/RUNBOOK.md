# SU-ERP — Setup & Run Guide

How to bring the whole system up on a fresh machine, provision the first users,
and run the demos. For architecture, see the root [README](../README.md); for
what's built vs designed, see [REMAINING_MODULES](REMAINING_MODULES.md).

---

## 1. Prerequisites

| Tool | Why | Notes |
|------|-----|-------|
| **Docker + Docker Compose v2** | runs the entire stack | the only hard requirement to *run* the system |
| Git | clone the repo | |
| Node 20 (via fnm/nvm) | only for frontend dev outside Docker | optional |
| Python 3.12 + [uv](https://docs.astral.sh/uv/) | only for running backend tests locally | optional |

You do **not** need Python or Node installed to run the system — everything runs
in containers.

> **Laptop CPU note.** The full stack is 30+ containers. The default `docker
> compose up` runs a **reduced profile** (~22 containers) that covers both demos
> and is comfortable on a laptop. Only add the `full` / `observability` profiles
> when you need them (see §6).

---

## 2. First-time startup

```bash
git clone <repo-url> Capstone
cd Capstone

# Build images and start the default profile (both demos, laptop-friendly).
docker compose -f infra/docker-compose.yml up --build -d
```

What happens automatically on first boot:
- Postgres creates all 13 service databases (via `infra/postgres/init-multi-db.sh`).
- Each Django service runs its migrations before serving.
- RabbitMQ, Redis, PgBouncer come up with health checks.

Give it ~1–2 minutes on first run (image builds + migrations). Check status:

```bash
docker compose -f infra/docker-compose.yml ps
```

> **Cold-start note.** The very first request to a service can be slow while its
> gunicorn worker warms up — an occasional `502` on the first hit is expected;
> retry once.

Endpoints once up:

| URL | What |
|-----|------|
| http://localhost:3001 | Web app (frontend) |
| http://localhost:8080 | API gateway (`/api/v1/...`) |
| http://localhost:8080/health | Gateway liveness |
| http://localhost:15672 | RabbitMQ management (guest / guest) |
| http://localhost:3000 | Grafana — only with the `observability` profile |
| http://localhost:9090 | Prometheus — only with the `observability` profile |

---

## 3. Bootstrap the platform superadmin (do this once)

The system is multi-tenant: every normal user belongs to an institution. Above
them sits a **platform superadmin** who creates institutions and their admins.
Create the first superadmin from the CLI:

```bash
docker compose -f infra/docker-compose.yml exec auth-service \
  python manage.py bootstrap_superadmin \
  --email super@suerp.io --password 'ChangeMe!Str0ng'
```

This creates an internal `platform` institution and a `superadmin` user in it.
Log in at http://localhost:3001/login with:
- **Institution:** `platform`
- **Email / Password:** what you passed above

From the superadmin screen you can create institutions and provision each
institution's admin — no CLI needed after this.

---

## 4. Provisioning institutions & users

### Option A — from the superadmin UI (recommended)
Log in as the superadmin → **Institutions** → create an institution, then add its
admin. That admin logs in (with the institution's slug) and adds their own users
(wardens, students, …) from the admin console.

### Option B — from the CLI
Provision an institution and its first admin in one command:

```bash
docker compose -f infra/docker-compose.yml exec auth-service \
  python manage.py create_institution \
  --slug demo-univ --name "Demo University" \
  --admin-email admin@demo.edu --admin-password 'Passw0rd!123'
```

Then that admin logs in at `/login` with institution `demo-univ` and manages
users from **Admin → Users**.

> Users are always scoped to an institution. Login always needs three fields:
> **institution slug, email, password.**

---

## 5. Running the demos

Both headline flows are described step-by-step in the root
[README](../README.md):
- **Saga** — student pays a hostel fee; allocation goes `pending → confirmed`
  across hostel ↔ finance ↔ notification.
- **ML escalation** — a grievance is scored by `ai-service` and auto-escalated.

Quick smoke test that the API is wired end-to-end:

```bash
# Log in (after creating demo-univ + its admin as in §4B)
curl -s -X POST localhost:8080/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"institution_slug":"demo-univ","email":"admin@demo.edu","password":"Passw0rd!123"}'
```

---

## 6. Compose profiles (control resource usage)

| Command | Runs |
|---------|------|
| `docker compose -f infra/docker-compose.yml up -d` | **default** — infra, gateway, frontend, and the services both demos need (auth, hostel, finance, notification, grievance, ai + their workers). ~22 containers. |
| `… --profile full up -d` | adds transport + the 7 prototype/stub services |
| `… --profile observability up -d` | adds Prometheus + Grafana |
| `… --profile full --profile observability up -d` | everything (30+ containers — heavy) |

Per-service tuning (already applied): celery runs `--concurrency=1`, gunicorn
`--workers 1`, to keep process count low on a laptop.

---

## 7. Everyday commands

```bash
# Follow logs for one service
docker compose -f infra/docker-compose.yml logs -f auth-service

# Restart a single service after a code change (rebuild its image)
docker compose -f infra/docker-compose.yml up -d --build finance-service

# Stop everything (keep data)
docker compose -f infra/docker-compose.yml down

# Stop and WIPE data (drops all DBs — next up re-creates + re-migrates them)
docker compose -f infra/docker-compose.yml down -v
```

---

## 8. Running tests

```bash
# Backend — per service (from the repo root)
cd services/auth-service && ../../.venv/bin/pytest -q

# Shared library
cd shared/libs/suerp_common && ../../../.venv/bin/pytest -q

# Frontend
cd frontend/su-erp-web && npm run test
```

CI (`.github/workflows/ci.yml`) runs lint + tests + security scan + docker build
for every service on push.

---

## 9. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `502` on the first request after boot | gunicorn worker cold start — retry once. |
| CPU pinned / laptop unusable | you started the `full`/`observability` profiles — use the default profile (§6). |
| `no such database: <svc>` | the Postgres volume predates a service being added. `down -v` then `up` re-runs the DB init for all 13. |
| CORS error in the browser console | the gateway allows `localhost`/`127.0.0.1` origins for dev. If the frontend runs on another host, add it to the `map $http_origin` block in `gateway/nginx.conf` and rebuild the gateway. |
| `Unknown institution` on login | the institution doesn't exist yet — create it (§3/§4). |
| Login `400` | login needs all three fields: institution slug, email, password. |

---

## 10. Before deploying beyond localhost (hardening)

The dev defaults are intentionally permissive. Before any non-local exposure:
- Set strong `JWT_SIGNING_KEY` / `SECRET_KEY` via env; fail loud when `DEBUG=0`.
- Lock the gateway CORS origin to the real frontend domain (not any localhost).
- Harden RabbitMQ credentials; pin image digests.
- See the "Known hardening TODOs" in the root README.
