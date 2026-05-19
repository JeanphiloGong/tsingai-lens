#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
COMPOSE_FILE="$ROOT_DIR/compose.yml"
ENV_FILE="$ROOT_DIR/.env"
BACKEND_ENV_FILE="$ROOT_DIR/backend.env"

usage() {
  cat <<'USAGE'
Usage: upgrade.sh vX.Y.Z

Updates LENS_VERSION in .env, pulls images, and restarts Lens.
USAGE
}

die() {
  printf 'upgrade: %s\n' "$*" >&2
  exit 1
}

set_env_key() {
  key="$1"
  value="$2"
  file="$3"
  tmp="${file}.tmp"

  if grep -q "^$key=" "$file"; then
    sed "s|^$key=.*|$key=$value|" "$file" > "$tmp"
    mv "$tmp" "$file"
  else
    printf '\n%s=%s\n' "$key" "$value" >> "$file"
  fi
}

version="${1:-}"
if [ -z "$version" ] || [ "$version" = "-h" ] || [ "$version" = "--help" ]; then
  usage
  [ -z "$version" ] && exit 1
  exit 0
fi

command -v docker >/dev/null 2>&1 || die "docker is required"
docker compose version >/dev/null 2>&1 || die "docker compose plugin is required"

[ -f "$ENV_FILE" ] || cp "$ROOT_DIR/.env.example" "$ENV_FILE"
[ -f "$BACKEND_ENV_FILE" ] || cp "$ROOT_DIR/backend.env.example" "$BACKEND_ENV_FILE"
mkdir -p "$ROOT_DIR/data/backend"

set_env_key LENS_VERSION "$version" "$ENV_FILE"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" pull
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d

printf 'Lens upgraded to %s\n' "$version"
