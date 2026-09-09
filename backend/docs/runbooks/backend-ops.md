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
export LENS_AGENT_MAX_TURN_SECONDS=300
export LENS_AGENT_MAX_TOOL_CALLS=24
export LENS_AGENT_MAX_MODEL_TOKENS=160000
export LENS_AGENT_NO_PROGRESS_LIMIT=2
export LENS_AGENT_EMERGENCY_MAX_CYCLES=64
export LENS_AGENT_MAX_PARALLEL_READS=4
export LENS_AGENT_MAX_MODEL_OUTPUT_TOKENS=16384
export LENS_AGENT_MAX_FINALIZATION_SECONDS=300
export LENS_AGENT_MAX_FINALIZATION_OUTPUT_TOKENS=8192
export LLM_REQUEST_TIMEOUT_SECONDS=180
export LLM_MAX_RETRIES=2
```

`CORE_EXTRACTION_MAX_CONCURRENCY` is optional. When unset, Core extraction uses
`4`.
`DOCUMENT_PREPARATION_MAX_CONCURRENCY` is optional. When unset, up to `10`
different Documents prepare concurrently in one backend process. The database
still admits only one active preparation Pipeline Run for the same Document.
`CORE_LLM_EXTRACTION_MODE` is optional. Supported values are `json_text` and
`provider_parse`. When unset, Core extraction uses `json_text`.
`LLM_REASONING_EFFORT` is optional and applies to both Core extraction and Chat,
including streamed Chat responses. Set it to a value supported by the model
provider, such as `none`, when a reasoning model must reserve its bounded
completion budget for structured output. When unset, the provider default is
used. A Chat request must not silently ignore this operator setting.
`LLM_MODEL` selects the model used by Core extraction and Research Agent Chat.
It must match one of the model ids returned by the configured OpenAI-compatible
endpoint, for example:

```bash
curl "$LLM_BASE_URL/models"
```

If the configured Research Agent model is unavailable, the turn returns
`model_unavailable` and no capability executes for that turn.
If the provider returns an empty, reasoning-only, or structurally invalid
streamed response, the runner retries once when no user-visible text was
received. A second invalid response returns `model_response_invalid`; this is
distinct from provider connectivity or availability failure.
The nine `LENS_AGENT_*` variables above are optional; the shown values are their
defaults. Time must be finite and positive; counts must be positive integers.
Invalid values are logged and use their defaults. These limits protect one
technical turn and do not measure scientific completeness. A new Source can
continue beyond six decisions. A batch with only previously seen observations
counts once toward the no-progress limit. Rewording a query that returns the
same successful Source observations is not progress. Different empty queries
and failures retain their requested scope; changed Source content, versions,
and pages remain new observations. This is a repetition guard, not a scientific
completeness judgment. Only explicitly parallel-safe reads share the
parallel-read allowance; writes always require exact approval.

Model calls, read/draft calls, and answer-only finalization share the turn
deadline. Finalization may use up to `LENS_AGENT_MAX_FINALIZATION_SECONDS`, but
only within the remaining turn time. It never starts after that deadline.
An awaited model timeout returns `failed` with `provider_timeout`, preserving
completed observations without issuing a second model request. If a read uses
the remaining time, its completed peers remain visible and the unavailable
final answer is reported as `final_answer_unavailable`. Approved writes retain
their existing completion and exact-approval rules; they are not forcibly
cancelled mid-mutation. Durable checkpoint I/O can also outlive the model/read
deadline.

`LENS_AGENT_MAX_MODEL_TOKENS` is an admission threshold for cumulative
provider-reported input plus output usage, not an exact billing ceiling. Usage
is known after a response, so the last admitted prompt can cross the threshold.
An already returned answer is preserved with `resource_budget` and scope
warnings when the threshold is reached, without an extra rewrite request.
Normal output is capped at the smaller of the remaining reported-token
allowance and `LENS_AGENT_MAX_MODEL_OUTPUT_TOKENS`. One answer-only request may
use its separate `LENS_AGENT_MAX_FINALIZATION_OUTPUT_TOKENS` allowance after
normal tool/token/cycle work stops, provided time remains. These generated-token
limits include reasoning tokens. A provider `length` finish reason is a
truncated response, not a completed answer or executable tool request.

Chat uses cancellable async model I/O and closes response streams on success,
error, and cancellation. There is no detached synchronous provider thread.
Closing local I/O does not guarantee immediate remote cancellation or zero
billing for an in-flight request. Chat disables hidden SDK retries;
`LLM_MAX_RETRIES` remains applicable to other model clients. The Runner owns
its one invalid-response retry and records usage from invalid responses when
available. Missing usage is counted explicitly; time, per-request output,
tools, and the emergency cycle ceiling still bound execution.

Successful finalization returns `completed` with a completion reason and scope
warnings; provider or finalization failures remain technical failures.
Structured cycle logs contain IDs, counts, usage, and termination reasons,
never full arguments, paper bodies, credentials, or hidden reasoning.

Streaming Chat sends an initial waiting event and a heartbeat every 15 seconds.
Heartbeats advance elapsed time while retaining the latest cycle and completed
tool counts. They indicate a live wait, not a new scientific observation.

## Initialize Or Upgrade The Schema

Alembic is the only schema authority. Application startup never creates or
changes tables:

```bash
alembic upgrade head
alembic current --check-heads
```

For a fresh development database, run the same commands. Historical SQLite or
JSON data is not imported by startup or by these migrations.

Check the schema revision of an existing replay database before starting a
real-model run. A missing `document_preparations` table with code at revision
`20260908_0055` indicates an incomplete upgrade, not unavailable scientific
evidence. Upgrade a disposable copy of the old database and compare Source,
Profile, Paper Map, Evidence, and Finding records before using it for replay.
Do not manually add columns or stamp the revision to bypass a failed migration.

The `0050`-`0055` aggregate migrations preserve existing PostgreSQL references
using native table alterations. Pre-merge Evidence and Finding child tables
are authoritative over stale analysis-summary copies. For a database already
upgraded with an older defective migration, editing that migration will not
rerun it: compare with a pre-upgrade backup before any recovery. Dropped child
records cannot safely be reconstructed from an empty summary.

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

Run the PostgreSQL migration tests only against a disposable database whose
name ends in `_test`; their fixtures reset its schema:

```bash
export LENS_TEST_DATABASE_URL='postgresql+psycopg://lens:<password>@localhost:5432/lens_test'
pytest -q tests/integration/persistence/test_migrations.py tests/integration/persistence/test_legacy_aggregate_migrations.py
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
  request returns after scheduling, and clients poll
  `GET /api/v1/pipeline-runs/{run_id}` for persisted progress. There is no
  dedicated executor queue or external task broker.
- Objective analysis starts as a process-local asyncio background task. An
  application semaphore allows four analyses to execute concurrently per
  backend process. Additional in-process tasks wait on that semaphore; this is
  concurrency admission, not a durable queue. Synchronous model and scientific
  computations run outside the event-loop thread, while all PostgreSQL access
  uses awaited task-local `AsyncSession` transactions. There is no dedicated
  Objective executor queue or external task broker; persisted Objective
  analysis rows remain the status authority used by the polling API.
- Startup marks orphaned queued or running Document preparation runs failed with
  the `interrupted` node and returns affected `processing` Documents to `stored`.
  Research-facing status reports this as `not_started`. The next preparation
  request is a new attempt and may reuse fingerprint-matching Source and Profile
  artifacts.
- Startup marks orphaned queued or running Objective analyses failed with
  `analysis_interrupted`. Unpublished interrupted work is exposed as
  `not_started`; any previously published analysis remains readable until a new
  analysis succeeds and is published atomically.
