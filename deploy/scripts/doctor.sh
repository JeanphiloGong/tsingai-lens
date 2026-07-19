#!/bin/sh
set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
COMPOSE_FILE="$ROOT_DIR/compose.yml"
ENV_FILE="$ROOT_DIR/.env"
BACKEND_ENV_FILE="$ROOT_DIR/backend.env"

FAIL_COUNT=0
WARN_COUNT=0

pass() {
  printf 'PASS %s\n' "$*"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  printf 'WARN %s\n' "$*" >&2
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf 'FAIL %s\n' "$*" >&2
}

fetch_url() {
  url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS "$url" >/dev/null
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$url" >/dev/null
  else
    return 2
  fi
}

load_env() {
  if [ -f "$ENV_FILE" ]; then
    set -a
    . "$ENV_FILE"
    set +a
  fi
}

if command -v docker >/dev/null 2>&1; then
  pass "docker command is available"
else
  fail "docker command is missing"
fi

if docker compose version >/dev/null 2>&1; then
  pass "docker compose plugin is available"
else
  fail "docker compose plugin is missing"
fi

if docker info >/dev/null 2>&1; then
  pass "docker daemon is reachable"
else
  fail "docker daemon is not reachable"
fi

[ -f "$COMPOSE_FILE" ] && pass "compose.yml exists" || fail "compose.yml is missing"
[ -f "$ENV_FILE" ] && pass ".env exists" || fail ".env is missing"
[ -f "$BACKEND_ENV_FILE" ] && pass "backend.env exists" || fail "backend.env is missing"

load_env
PASSWORD_READY=0
if printf '%s' "${POSTGRES_PASSWORD:-}" | grep -Eq '^[0-9A-Fa-f]{64}$'; then
  pass "POSTGRES_PASSWORD is configured"
  PASSWORD_READY=1
else
  fail "POSTGRES_PASSWORD must contain 64 hexadecimal characters; generate it with: openssl rand -hex 32"
fi

mkdir -p "$ROOT_DIR/data/backend" 2>/dev/null || true
if [ -d "$ROOT_DIR/data/backend" ] && [ -w "$ROOT_DIR/data/backend" ]; then
  pass "backend data directory is writable"
else
  fail "backend data directory is not writable"
fi

COMPOSE_READY=0
if [ -f "$ENV_FILE" ] && [ -f "$BACKEND_ENV_FILE" ] && [ "$PASSWORD_READY" -eq 1 ]; then
  if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config -q >/dev/null 2>&1; then
    pass "compose config is valid"
    COMPOSE_READY=1
  else
    fail "compose config is invalid"
  fi
fi

LENS_HTTP_PORT="${LENS_HTTP_PORT:-8080}"

if [ "$COMPOSE_READY" -eq 1 ]; then
  RUNNING_SERVICES=$(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps --status running --services 2>/dev/null)

  if [ -z "$RUNNING_SERVICES" ]; then
    warn "Lens containers are not running; run ./scripts/lens up"
  else
    if printf '%s\n' "$RUNNING_SERVICES" | grep -qx postgres; then
      pass "postgres container is running"
      if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T postgres pg_isready -U lens -d lens >/dev/null 2>&1; then
        pass "postgres accepts connections"
      else
        fail "postgres is running but not ready"
      fi
    else
      fail "postgres container is not running"
    fi

    if printf '%s\n' "$RUNNING_SERVICES" | grep -qx backend; then
      if docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T backend alembic current --check-heads >/dev/null 2>&1; then
        pass "database migration is at the Alembic head"
      else
        fail "backend cannot verify the Alembic head; run the documented migration command"
      fi
    else
      warn "backend container is not running; Alembic state was not checked"
    fi

    if printf '%s\n' "$RUNNING_SERVICES" | grep -qx frontend; then
      if fetch_url "http://localhost:$LENS_HTTP_PORT" >/dev/null 2>&1; then
        pass "frontend is reachable on port $LENS_HTTP_PORT"
      else
        warn "frontend container is running but http://localhost:$LENS_HTTP_PORT is not reachable"
      fi

      if fetch_url "http://localhost:$LENS_HTTP_PORT/api/openapi.json" >/dev/null 2>&1; then
        pass "backend API is reachable through the frontend proxy"
      else
        warn "backend API is not reachable through the frontend proxy"
      fi
    else
      warn "frontend container is not running"
    fi
  fi
fi

if [ "$FAIL_COUNT" -gt 0 ]; then
  printf 'Doctor failed with %s failure(s) and %s warning(s).\n' "$FAIL_COUNT" "$WARN_COUNT" >&2
  exit 1
fi

printf 'Doctor completed with %s warning(s).\n' "$WARN_COUNT"
