#!/usr/bin/env bash
# Creates one database per backend service on first container init.
# postgres:16's docker-entrypoint-initdb.d runs this automatically (executable .sh files).
set -euo pipefail

SERVICE_DATABASES="auth hostel finance transport grievance notification student attendance exam library canteen placement analytics"

for db in $SERVICE_DATABASES; do
	echo "Creating database '${db}' (owner: ${POSTGRES_USER})..."
	psql -v ON_ERROR_STOP=1 --username "${POSTGRES_USER}" --dbname "postgres" <<-EOSQL
		SELECT 'CREATE DATABASE "${db}" OWNER "${POSTGRES_USER}"'
		WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${db}')\gexec
	EOSQL
done
