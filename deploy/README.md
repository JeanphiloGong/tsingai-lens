# TsingAI-Lens Deploy Bundle

This directory is the minimal self-hosted runtime bundle for Lens. It uses
published Docker images instead of building from the source tree.

## Prerequisites

- Docker Engine
- Docker Compose plugin (`docker compose`)

## One-Line Install

Install the deploy bundle with:

```bash
curl -fsSL https://raw.githubusercontent.com/JeanphiloGong/tsingai-lens/main/deploy/install.sh \
  | sh -s -- --version v0.8.0 --ref v0.8.0
```

Use `--ref <git-ref>` when you want the deploy files themselves to come from a
specific branch or tag.

Then run:

```bash
cd lens-deploy
./scripts/lens doctor
./scripts/lens up
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

## Manual Configure

```bash
cp .env.example .env
cp backend.env.example backend.env
```

Edit `.env` to choose the published image tag and host port:

```bash
LENS_VERSION=v0.8.0
LENS_HTTP_PORT=8080
```

Edit `backend.env` before the first v0.8.0 start to create the initial login
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

## Run

```bash
./scripts/lens up
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
./scripts/lens upgrade v0.8.0
```

Command mapping:

- `doctor` checks Docker, Compose, config files, the data directory, and
  frontend/backend reachability.
- `up` runs `docker compose up -d`.
- `down` runs `docker compose down`.
- `logs` follows `docker compose logs`.
- `ps` runs `docker compose ps`.
- `pull` pulls the configured images.
- `upgrade TAG` writes `LENS_VERSION=TAG`, pulls images, and restarts Lens.

## Upgrade

Back up runtime data before changing versions:

```bash
cp -a data/backend data/backend.backup.$(date +%Y%m%d%H%M%S)
```

Then upgrade:

```bash
./scripts/lens upgrade v0.8.0
./scripts/lens doctor
```

## Data

Runtime data is stored under:

```text
data/backend/
```

Back up this directory before replacing the deploy bundle or changing versions.
