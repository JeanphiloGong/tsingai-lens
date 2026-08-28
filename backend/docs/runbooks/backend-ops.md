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

The URL is required, must use the `postgresql+psycopg` dialect, and must name a
database. The backend constructs it with SQLAlchemy `create_async_engine`,
which selects psycopg's async implementation for this URL. Keep credentials in
`backend/.env` or the shell; never commit them.

Set backend LLM runtime variables before local runs that invoke model-backed
features:

```bash
export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=qwen1.5-8b-chat
export LLM_API_KEY=sk-local
export LLM_REASONING_EFFORT=none
export CORE_LLM_EXTRACTION_MODE=json_text
export DOCUMENT_PREPARATION_MAX_CONCURRENCY=10
export CORE_EXTRACTION_MAX_CONCURRENCY=4
```

`CORE_EXTRACTION_MAX_CONCURRENCY` is optional. When unset, Core extraction uses
`4`.
`DOCUMENT_PREPARATION_MAX_CONCURRENCY` is optional. When unset, up to `10`
different Documents prepare concurrently in one backend process. The database
still admits only one active preparation task for the same Document.
`CORE_LLM_EXTRACTION_MODE` is optional. Supported values are `json_text` and
`provider_parse`. When unset, Core extraction uses `json_text`.
`LLM_REASONING_EFFORT` is optional. Set it to a value supported by the model
provider, such as `none`, when a reasoning model must reserve its bounded
completion budget for structured JSON output. When unset, the provider default
is used.
`LLM_MODEL` selects the model used by Core extraction and Research Agent Chat.
It must match one of the model ids returned by the configured OpenAI-compatible
endpoint, for example:

```bash
curl "$LLM_BASE_URL/models"
```

If the configured Research Agent model is unavailable, the turn returns
`model_unavailable` and no capability executes for that turn.

## Initialize Or Upgrade The Schema

Alembic is the only schema authority. Application startup never creates or
changes tables:

```bash
alembic upgrade head
alembic current --check-heads
```

The maintained migration history is one explicit current-schema baseline. It is
for a fresh or deliberately reset database; it is not an in-place upgrade path
from an earlier Lens schema. When a test or development database contains an
older revision, recreate that disposable database and run `alembic upgrade
head`. Historical PostgreSQL, SQLite, or JSON data is not imported or preserved
by startup or by this baseline.

`alembic downgrade base` removes the entire baseline schema. Run downgrade only
against a disposable database whose name ends in `_test`, as shown in the
verification section below.

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

- Application log timestamps use China Standard Time and include the explicit
  `+0800` offset. Persisted domain and runtime timestamps remain UTC.
- Structured product state persists in PostgreSQL. `backend/data` holds
  immutable object bytes and disposable runtime scratch.
- Document preparation creates Source runtime settings from the owning
  Document's stored bytes and environment variables; no `default.yaml` file is
  required in Docker volumes.
- Public HTTP paths are split between `/api/*` for docs and static assets and
  `/api/v1/*` for business APIs.
- Clients read readiness per Document. Ready papers may be selected for
  Objective discovery or analysis while other papers remain stored, processing,
  or failed.
- Document preparation starts as a process-local asyncio background task. The
  request returns after scheduling, and clients poll `GET /api/v1/tasks/{task_id}`
  for persisted progress. There is no dedicated executor queue or external task
  broker.
- Objective analysis starts as a process-local asyncio background task. An
  application semaphore allows four analyses to execute concurrently per
  backend process. Additional in-process tasks wait on that semaphore; this is
  concurrency admission, not a durable queue. Synchronous model and scientific
  computations run outside the event-loop thread, while all PostgreSQL access
  uses awaited task-local `AsyncSession` transactions. There is no dedicated
  Objective executor queue or external task broker; persisted Objective
  analysis rows remain the status authority used by the polling API.
- Startup marks orphaned queued or running Document preparation failed with the
  `interrupted` stage and returns affected `processing` Documents to `stored`.
  Research-facing status reports this as `not_started`. The next preparation
  request is a new attempt and may reuse fingerprint-matching Source and Profile
  artifacts.
- Startup marks orphaned queued or running Objective analyses failed with
  `analysis_interrupted`. Unpublished interrupted work is exposed as
  `not_started`; any previously published analysis remains readable until a new
  analysis succeeds and is published atomically.
