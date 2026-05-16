# TsingAI-Lens Deploy Bundle

This directory is the minimal self-hosted runtime bundle for Lens. It uses
published Docker images instead of building from the source tree.

## Prerequisites

- Docker Engine
- Docker Compose plugin (`docker compose`)

## Configure

```bash
cp .env.example .env
cp backend.env.example backend.env
```

Edit `backend.env` when you want Lens to call an OpenAI-compatible LLM or
embedding endpoint.

## Run

```bash
docker compose --env-file .env -f compose.yml up -d
```

Open:

```text
http://localhost:8080
```

## Stop

```bash
docker compose --env-file .env -f compose.yml down
```

## Data

Runtime data is stored under:

```text
data/backend/
```

Back up this directory before replacing the deploy bundle or changing versions.
