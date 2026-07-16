PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: up down test lint fmt install-common test-concurrency chaos

up:
	docker compose -f infra/docker-compose.yml up --build

down:
	docker compose -f infra/docker-compose.yml down -v

install-common:
	$(PIP) install -e ./shared/libs/suerp_common

lint:
	.venv/bin/ruff check services shared && .venv/bin/black --check services shared && .venv/bin/isort --check services shared

fmt:
	.venv/bin/ruff check --fix services shared && .venv/bin/black services shared && .venv/bin/isort services shared

test:
	.venv/bin/pytest shared services

# Row-lock contention proofs. These need real Postgres (they skip on the SQLite
# fallback, where select_for_update() is a no-op and a pass would prove nothing)
# and connect directly on 5432 — PgBouncer's transaction pooling can't proxy the
# CREATE DATABASE that Django's test runner needs.
test-concurrency:
	cd services/hostel-service && \
	DATABASE_URL=postgres://suerp:suerp@localhost:5432/hostel \
	JWT_SIGNING_KEY=dev-insecure-change-me \
	../../.venv/bin/pytest hostel/tests/test_concurrency.py -v

# Kills RabbitMQ mid-saga against the running compose stack and asserts the
# outbox recovers. Restarts the broker on exit, including on interrupt.
chaos:
	./scripts/chaos_broker_outage.sh
