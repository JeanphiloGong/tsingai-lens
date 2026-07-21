# Backend Local Development and Operations

## Environment Setup

```bash
cd backend
uv venv .venv
source .venv/bin/activate
uv sync
```

## Required Runtime Variables

Set the PostgreSQL URL before any backend command that constructs persistence:

```bash
export LENS_DATABASE_URL='postgresql+psycopg://lens:<password>@localhost:5432/lens-postgres-dev'
```

The URL is required, must use the synchronous `postgresql+psycopg` driver, and
must name a database. Keep credentials in `backend/.env` or the shell; never
commit them.

Set backend LLM runtime variables before local runs that invoke model-backed
features:

```bash
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=qwen1.5-8b-chat
export GOAL_COPILOT_LLM_MODEL=qwen1.5-8b-chat
export LLM_API_KEY=sk-local
export CORE_LLM_EXTRACTION_MODE=json_text
export CORE_EXTRACTION_MAX_CONCURRENCY=4
```

`CORE_EXTRACTION_MAX_CONCURRENCY` is optional. When unset, Core extraction uses
`4`.
`CORE_LLM_EXTRACTION_MODE` is optional. Supported values are `json_text` and
`provider_parse`. When unset, Core extraction uses `json_text`.
`GOAL_COPILOT_LLM_MODEL` is optional. When unset, goal chat uses `LLM_MODEL`;
when set, it must match one of the model ids returned by the configured
OpenAI-compatible endpoint, for example:

```bash
curl "$LLM_BASE_URL/models"
```

If the goal copilot model name does not match the served model id, goal chat
returns `goal_copilot_model_unavailable`. In that state Lens deliberately
refuses to save AI-generated experiment plans from the message, because those
plans require a `collection_grounded` answer with source links and the
`protocol_ready_findings` review gate.

## Initialize Or Upgrade The Schema

Alembic is the only schema authority. Application startup never creates or
changes tables:

```bash
alembic upgrade head
alembic current --check-heads
```

For a fresh development database, run the same commands. Historical SQLite or
JSON data is not imported by startup or by these migrations.

## Start the Backend

```bash
uvicorn main:app --reload --port 8010
```

Primary local endpoints:

- API docs: `http://localhost:8010/api/docs`
- OpenAPI: `http://localhost:8010/api/openapi.json`

## Common Verification Commands

```bash
pytest -q
python3 ../scripts/check_docs_governance.py
```

Run the PostgreSQL migration lifecycle test only against a disposable database
whose name ends in `_test`; the test intentionally downgrades it:

```bash
export LENS_TEST_DATABASE_URL='postgresql+psycopg://lens:<password>@localhost:5432/lens_test'
pytest -q tests/integration/persistence/test_migrations.py
LENS_DATABASE_URL="$LENS_TEST_DATABASE_URL" alembic upgrade head
LENS_DATABASE_URL="$LENS_TEST_DATABASE_URL" alembic current --check-heads
```

For the supported Compose deployment, health diagnosis, upgrade, backup, and
restore procedures, use [`../../../deploy/README.md`](../../../deploy/README.md).
That document is the deployment operations authority; this runbook does not
duplicate its destructive restore commands.

## Operational Notes

- Structured product state persists in PostgreSQL. `backend/data` holds
  immutable object bytes, collection workspaces, and rebuildable scratch.
- Collection build creates Source runtime settings from collection paths and
  environment variables; no `default.yaml` file is required in Docker volumes.
- Public HTTP paths are split between `/api/*` for docs and static assets and
  `/api/v1/*` for business APIs.
- Collection artifact readiness should be checked before calling graph
  endpoints from clients.
- Collection build tasks run in a dedicated single-worker thread inside the
  backend process. The task creation request returns after queueing, and
  clients should poll `GET /api/v1/tasks/{task_id}` for progress.
