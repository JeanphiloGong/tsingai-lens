#!/bin/sh
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=${LENS_DEPLOY_DIR:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)}
set -a
. "$ROOT_DIR/.env"
set +a

if ! printf '%s' "${LENS_USERS_PASSWORD:-}" | grep -Eq '^[0-9A-Fa-f]{64}$'; then
  printf 'LENS_USERS_PASSWORD must be 64 hexadecimal characters.\n' >&2
  exit 1
fi

# Existing roles retain their passwords; changing .env is not credential rotation.
docker compose --project-directory "$ROOT_DIR" --env-file "$ROOT_DIR/.env" -f "$ROOT_DIR/compose.yml" \
  exec -T -e LENS_USERS_PASSWORD postgres psql -U lens -d postgres -v ON_ERROR_STOP=1 <<'SQL'
\getenv identity_password LENS_USERS_PASSWORD
SELECT format('CREATE ROLE lens_users LOGIN PASSWORD %L', :'identity_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lens_users')
\gexec
SELECT 'CREATE DATABASE lens_users OWNER lens_users'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'lens_users')
\gexec
SQL
