# TsingAI-Lens Deploy Bundle

This directory is the minimal self-hosted runtime bundle for Lens. It runs the
published Lens images with one internal PostgreSQL service.

This is the repository's only Docker Compose entrypoint. For source-tree
development, use the module-local instructions in
[`backend/README.md`](../backend/README.md) and
[`frontend/README.md`](../frontend/README.md).

## Prerequisites

- Docker Engine with the Docker Compose plugin (`docker compose`) is the
  default runtime.
- Podman can be used with `podman compose`; use the
  [Podman Runtime](#podman-runtime) commands because `./scripts/lens` calls
  Docker Compose.

## One-Line Install

Install the deploy bundle with:

```bash
curl -fsSL https://raw.githubusercontent.com/JeanphiloGong/tsingai-lens/main/deploy/install.sh \
  | sh -s -- --version v0.10.1 --ref v0.10.1
```

Use `--ref <git-ref>` when you want the deploy files themselves to come from a
specific branch or tag.

Before the first start, generate the database password:

```bash
openssl rand -hex 32
```

Put the output in `POSTGRES_PASSWORD` in `.env`. Then edit `backend.env` to set
the bootstrap admin account and any LLM or embedding environment variables.
See [Manual Configure](#manual-configure).

Then run:

```bash
cd lens-deploy
./scripts/lens doctor
docker compose --env-file .env -f compose.yml up -d postgres
docker compose --env-file .env -f compose.yml run --rm backend alembic upgrade head
./scripts/lens up
./scripts/lens doctor
```

Open:

```text
http://localhost:8080
```

## How The Script Works

`./scripts/lens` is a small POSIX shell command wrapper, not a Makefile.

It keeps the deploy commands short and always calls Docker Compose with the
same env file and compose file:

```bash
docker compose --env-file .env -f compose.yml <command>
```

For example:

```bash
./scripts/lens up
```

is the deployment wrapper around:

```bash
docker compose --env-file .env -f compose.yml up -d
```

The wrapper also creates missing runtime files and directories when needed:

- `.env`
- `backend.env`
- `data/backend/`

Schema migrations remain explicit. `./scripts/lens up` does not run Alembic.
Also, do not publish the output of `./scripts/lens config`: the rendered backend
environment contains the database connection URL.

## Podman Runtime

Use this path on machines without Docker. Run the Compose commands directly
with Podman from the deploy bundle directory:

```bash
cd lens-deploy
podman compose --env-file .env -f compose.yml pull
podman compose --env-file .env -f compose.yml up -d postgres
podman compose --env-file .env -f compose.yml run --rm backend alembic upgrade head
podman compose --env-file .env -f compose.yml up -d
podman compose --env-file .env -f compose.yml ps
```

Useful Podman equivalents:

```bash
podman compose --env-file .env -f compose.yml logs -f
podman compose --env-file .env -f compose.yml restart backend
podman compose --env-file .env -f compose.yml down
```

The backend data volume uses the SELinux relabel option `:Z`:

```yaml
./data/backend:/app/data:Z
```

This lets Podman write runtime data on SELinux Enforcing hosts such as Fedora,
RHEL, and CentOS. Without that label the backend can fail with
`PermissionError` while creating `/app/data/collections`, and the frontend will
show `502 Bad Gateway` because nginx cannot reach the backend.

When the backend container needs to call a vLLM server running on the host,
start vLLM so it listens beyond host-local loopback, then point Lens at the
Podman host gateway:

```bash
uv run vllm-control start --host 0.0.0.0
```

```bash
LLM_BASE_URL=http://host.containers.internal:8008/v1
LLM_MODEL=<served-model-name>
LLM_API_KEY=not-needed
```

Keep `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`, and `EMBEDDING_API_KEY` empty
unless the configured service exposes an OpenAI-compatible embeddings endpoint.

## Manual Configure

```bash
cp .env.example .env
cp backend.env.example backend.env
```

Generate a 64-character hexadecimal database password:

```bash
openssl rand -hex 32
```

Edit `.env` to set that generated value, the published image tag, and the host
port:

```bash
LENS_VERSION=v0.10.1
LENS_HTTP_PORT=8080
POSTGRES_PASSWORD=<generated-64-character-hex-value>
```

The password initializes the `lens` database user only when the PostgreSQL
volume is empty. Changing `.env` later does not rotate an existing database
password. Keep `.env` private and do not commit it.

Edit `backend.env` before the first v0.10.1 start to create the initial login
user:

```bash
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=change-this-password
BOOTSTRAP_ADMIN_NAME=Admin
```

`BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` are read only when the
backend starts. If the user already exists, the backend keeps the existing
account.

Also edit `backend.env` when you want Lens to call an OpenAI-compatible LLM or
embedding endpoint:

```bash
LLM_BASE_URL=
LLM_MODEL=
LLM_API_KEY=

EMBEDDING_BASE_URL=
EMBEDDING_MODEL=
EMBEDDING_API_KEY=
```

`LENS_DATABASE_URL` is injected by `compose.yml`; do not add it to
`backend.env`.

## Initialize Database

Start PostgreSQL, apply the Alembic migrations explicitly, and then start Lens:

```bash
./scripts/lens doctor
docker compose --env-file .env -f compose.yml up -d postgres
docker compose --env-file .env -f compose.yml run --rm backend alembic upgrade head
./scripts/lens up
```

Application startup never creates or changes database schema.

## Run

```bash
./scripts/lens up
./scripts/lens doctor
./scripts/lens ps
```

Open:

```text
http://localhost:8080
```

## Stop

```bash
./scripts/lens down
```

## Useful Commands

```bash
./scripts/lens doctor
./scripts/lens logs
./scripts/lens ps
./scripts/lens pull
./scripts/lens upgrade v0.10.1
```

Command mapping:

- `doctor` checks Docker, Compose, password shape, PostgreSQL readiness,
  Alembic head state, the data directory, and frontend/backend reachability.
- `up` runs `docker compose up -d`.
- `down` runs `docker compose down`.
- `logs` follows `docker compose logs`.
- `ps` runs `docker compose ps`.
- `pull` pulls the configured images.
- `upgrade TAG` writes `LENS_VERSION=TAG`, pulls images, and restarts Lens; use
  the sequence below for releases with database migrations.

## Upgrade

Back up PostgreSQL and file-backed runtime data before changing versions. See
[Backup](#backup) for the database command, then copy the file-backed data:

```bash
cp -a data/backend data/backend.backup.$(date +%Y%m%d%H%M%S)
```

Edit `LENS_VERSION` in `.env`, stop the application, pull the new images,
migrate with the new backend image, and start Lens again:

```bash
docker compose --env-file .env -f compose.yml stop frontend backend
docker compose --env-file .env -f compose.yml pull
docker compose --env-file .env -f compose.yml up -d postgres
docker compose --env-file .env -f compose.yml run --rm backend alembic upgrade head
docker compose --env-file .env -f compose.yml up -d
./scripts/lens doctor
```

## Backup

Write a custom-format PostgreSQL archive outside the deploy bundle:

```bash
mkdir -p ../lens-backups
lens_backup_file="../lens-backups/lens-$(date +%Y%m%d%H%M%S).dump"
docker compose --env-file .env -f compose.yml exec -T postgres \
  pg_dump --format=custom --no-owner --no-acl --username=lens --dbname=lens \
  > "$lens_backup_file"
test -s "$lens_backup_file"
```

Keep the matching `data/backend/` backup with the database archive when a Lens
version still owns file-backed structured state.

## Restore

Restore only from a trusted, non-empty archive. This procedure stops the
backend, replaces the `lens` database, verifies the Alembic head, and then
starts the backend again:

```bash
lens_backup_file=../lens-backups/lens-YYYYMMDDHHMMSS.dump
test -s "$lens_backup_file"
docker compose --env-file .env -f compose.yml stop backend
docker compose --env-file .env -f compose.yml exec -T postgres \
  psql --set=ON_ERROR_STOP=1 --username=lens --dbname=postgres \
  --command='DROP DATABASE IF EXISTS lens WITH (FORCE)' \
  --command='CREATE DATABASE lens WITH TEMPLATE template0 OWNER lens'
docker compose --env-file .env -f compose.yml exec -T postgres \
  pg_restore --exit-on-error --single-transaction --no-owner --no-acl \
  --username=lens --dbname=lens < "$lens_backup_file"
docker compose --env-file .env -f compose.yml run --rm backend \
  alembic current --check-heads
docker compose --env-file .env -f compose.yml start backend
./scripts/lens doctor
```

## Data

Structured database state is stored in the Compose-managed `postgres-data`
volume. Remaining file-backed runtime data is stored under:

```text
data/backend/
```

`docker compose down` preserves both. `docker compose down --volumes`
permanently deletes the PostgreSQL volume; use it only when intentionally
discarding all database state. Back up both authorities before replacing the
deploy bundle or changing versions.
