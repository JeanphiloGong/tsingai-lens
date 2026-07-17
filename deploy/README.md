# TsingAI-Lens Deploy Bundle

This directory is the minimal self-hosted runtime bundle for Lens. It uses
published Docker images instead of building from the source tree.

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
  | sh -s -- --version v0.9.0 --ref v0.9.0
```

Use `--ref <git-ref>` when you want the deploy files themselves to come from a
specific branch or tag.

Before the first start, edit `backend.env` to set the bootstrap admin account
and any LLM or embedding environment variables. See [Manual Configure](#manual-configure).

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

## Podman Runtime

Use this path on machines without Docker. Run the Compose commands directly
with Podman from the deploy bundle directory:

```bash
cd lens-deploy
podman compose --env-file .env -f compose.yml pull
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

Edit `.env` to choose the published image tag and host port:

```bash
LENS_VERSION=v0.9.0
LENS_HTTP_PORT=8080
```

Edit `backend.env` before the first v0.9.0 start to create the initial login
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
./scripts/lens upgrade v0.9.0
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
./scripts/lens upgrade v0.9.0
./scripts/lens doctor
```

## Data

Runtime data is stored under:

```text
data/backend/
```

Back up this directory before replacing the deploy bundle or changing versions.
