#!/bin/sh
set -eu
umask 077

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BUNDLE_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
ROOT_DIR=${LENS_DEPLOY_DIR:-$BUNDLE_DIR}
version=${1:-}
if ! printf '%s' "$version" | grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+$'; then
  printf 'Usage: upgrade.sh vX.Y.Z\n' >&2
  exit 1
fi
for file in .env backend.env user-service.env compose.yml; do
  [ -f "$ROOT_DIR/$file" ] || { printf 'Missing runtime file: %s\n' "$file" >&2; exit 1; }
done
set -a
. "$ROOT_DIR/.env"
set +a

current_compose() {
  docker compose --project-directory "$ROOT_DIR" --env-file "$ROOT_DIR/.env" -f "$ROOT_DIR/compose.yml" "$@"
}
# The checked-out release bundle may be separate from private runtime files.
target_compose() {
  LENS_VERSION="$version" docker compose --project-directory "$ROOT_DIR" --env-file "$ROOT_DIR/.env" -f "$BUNDLE_DIR/compose.yml" "$@"
}

current_compose config -q
legacy=$(current_compose exec -T postgres psql -U lens -d lens -Atc "SELECT to_regclass('public.auth_users') IS NOT NULL")
if [ "$legacy" != f ]; then
  printf 'Legacy identity tables remain. Complete the documented stopped-write account import and 0099 cutover before routine upgrade.\n' >&2
  exit 1
fi
target_compose config -q
target_services=$(target_compose config --services)
target_compose pull

mkdir -p "$ROOT_DIR/backups"
backup=$(mktemp -d "$ROOT_DIR/backups/$(date -u +%Y%m%dT%H%M%SZ)-$version.XXXXXX")
printf 'Maintenance backup: %s\n' "$backup"
finished=false
backup_ready=false
on_exit() {
  result=$?
  if [ "$finished" != true ]; then
    for service in $target_services; do
      [ "$service" = postgres ] || target_compose stop "$service" >/dev/null 2>&1 || true
    done
    if [ "$backup_ready" = true ]; then
      printf 'Upgrade stopped in maintenance mode. Restore %s with the matching old images/configuration; no schema downgrade was attempted.\n' "$backup" >&2
    else
      printf 'Backup is incomplete; no migration was started. Keep maintenance mode and inspect %s.\n' "$backup" >&2
    fi
  fi
  exit "$result"
}
trap on_exit EXIT

services=$(current_compose config --services)
for service in $services; do
  [ "$service" = postgres ] || current_compose stop "$service"
done
current_compose exec -T postgres pg_dump -U lens -Fc lens > "$backup/lens.dump"
current_compose exec -T postgres pg_dump -U lens -Fc lens_users > "$backup/lens_users.dump"
current_compose exec -T postgres pg_restore --list < "$backup/lens.dump" > /dev/null
current_compose exec -T postgres pg_restore --list < "$backup/lens_users.dump" > /dev/null
tar -czf "$backup/runtime.tgz" -C "$ROOT_DIR" .env backend.env user-service.env compose.yml scripts identity-certs public-tls
tar -czf "$backup/resources.tgz" -C "$ROOT_DIR" data/backend
backup_ready=true

if [ "$BUNDLE_DIR" != "$ROOT_DIR" ]; then
  for file in compose.yml .env.example backend.env.example user-service.env.example README.md install.sh; do
    cp "$BUNDLE_DIR/$file" "$ROOT_DIR/$file"
  done
  for file in lens doctor.sh upgrade.sh prepare-identity.sh; do
    cp "$BUNDLE_DIR/scripts/$file" "$ROOT_DIR/scripts/$file"
  done
fi
LENS_DEPLOY_DIR="$ROOT_DIR" "$ROOT_DIR/scripts/prepare-identity.sh"
export GOOSE_DBSTRING="postgres://lens_users:${LENS_USERS_PASSWORD:?Set LENS_USERS_PASSWORD}@postgres:5432/lens_users"
target_compose run --rm --no-deps -e GOOSE_DRIVER=postgres -e GOOSE_DBSTRING --entrypoint goose user-service -dir /app/migrations up
target_compose run --rm --no-deps backend alembic upgrade head
target_compose up -d --wait --wait-timeout 180
LENS_VERSION="$version" LENS_DEPLOY_DIR="$ROOT_DIR" "$ROOT_DIR/scripts/doctor.sh" --running

# Persist the selected tag only after the candidate stack passes verification.
sed "s/^LENS_VERSION=.*/LENS_VERSION=$version/" "$ROOT_DIR/.env" > "$ROOT_DIR/.env.next"
mv "$ROOT_DIR/.env.next" "$ROOT_DIR/.env"
finished=true
printf 'Lens upgraded to %s; backup retained at %s\n' "$version" "$backup"
