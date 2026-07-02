PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: up down test lint fmt install-common

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
