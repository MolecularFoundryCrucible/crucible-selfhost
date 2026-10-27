#!/bin/bash
# Runs once, as the PostgreSQL superuser, when the database volume is first created.
# The API connects as the ordinary role "crucible", which owns the database; the extensions it
# needs are created here because "vector" requires a superuser.
set -euo pipefail

secret=/run/secrets/PGDB_PW
if [ ! -r "$secret" ] || [ -z "$(tr -d '[:space:]' < "$secret")" ]; then
  echo "crucible: $secret is missing, empty, or not readable by the database container (run: chmod 644 secrets/*)" >&2
  exit 1
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\set app_password `tr -d '[:space:]' < /run/secrets/PGDB_PW`
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE ROLE crucible LOGIN PASSWORD :'app_password';
ALTER DATABASE crucible OWNER TO crucible;
SQL
