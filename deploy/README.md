# TsingAI-Lens Deploy Bundle

This directory is the minimal self-hosted runtime bundle for Lens. It uses
published Docker images instead of building from the source tree.

## Prerequisites

- Docker Engine
- Docker Compose plugin (`docker compose`)

## One-Line Install

Install the deploy bundle with:

```bash
curl -fsSL https://raw.githubusercontent.com/JeanphiloGong/tsingai-lens/main/deploy/install.sh | sh -s -- --version v0.4.0
```

Use `--ref <git-ref>` when you want the deploy files themselves to come from a
specific branch or tag.

Then run:

```bash
cd lens-deploy
./scripts/lens doctor
./scripts/lens up
```

## Manual Configure

```bash
cp .env.example .env
cp backend.env.example backend.env
```

Edit `backend.env` when you want Lens to call an OpenAI-compatible LLM or
embedding endpoint.

## Run

```bash
./scripts/lens up
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
./scripts/lens upgrade v0.4.0
```

## Data

Runtime data is stored under:

```text
data/backend/
```

Back up this directory before replacing the deploy bundle or changing versions.
