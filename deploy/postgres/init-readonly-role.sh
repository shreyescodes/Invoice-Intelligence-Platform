#!/usr/bin/env bash
# Runs once, when the Postgres volume is first initialised. The migrations grant this role SELECT on
# the analytics_* views only, so natural-language queries cannot read anything else.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
  CREATE ROLE iip_readonly LOGIN PASSWORD '${READONLY_PASSWORD:-readonly}' NOSUPERUSER NOCREATEDB NOCREATEROLE;
  ALTER ROLE iip_readonly SET default_transaction_read_only = on;
  ALTER ROLE iip_readonly SET statement_timeout = '5s';
  GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO iip_readonly;
  GRANT USAGE ON SCHEMA public TO iip_readonly;
SQL
