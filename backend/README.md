# TsingAI-Lens Backend

FastAPI backend for document ingestion, document-level research preparation,
selected-paper Objective discovery, evidence-backed Objective analysis, and
published Finding review.

## Current Research Flow

```text
Collection
  -> current Documents

Document
  -> SourceDocument
  -> DocumentProfile

selected ready Documents
  -> lightweight PaperMap (lazy, for discovery navigation)
  -> Objective candidates

confirmed Objective + selected ready Documents
  -> reusable per-document Evidence inspection
  -> ObjectiveEvidence
  -> cross-document Findings
```

A Collection groups papers. It does not own a generated snapshot. Each Document
owns its current preparation status and current Source and Profile. A Paper Map
is a lazy, document-scoped navigation artifact built by Objective discovery or
analysis for the explicitly selected ready Documents. Adding or retrying one
paper never rebuilds unrelated papers or maps.
Objective analysis likewise reuses completed inspection for unchanged papers and
retries only papers whose inspection is missing, failed, or stale.

## Ownership Map

- `controllers/`: HTTP routes and response schemas.
- `application/source/`: Collection lifecycle, upload, per-document preparation,
  task state, and Source reads.
- `application/core/`: Document profiling, Paper Map creation, Objective
  discovery, Evidence extraction, and Finding synthesis.
- `application/chat/`: Research Agent trajectory and approved capability calls.
- `domain/`: Domain records, invariants, and repository ports.
- `infra/`: PostgreSQL, object storage, Source parsing, and model clients.
- `docs/`: Backend architecture, API, and operations authorities.

## Public HTTP Contract

- Business APIs: `/api/v1/*`
- OpenAPI: `/api/openapi.json`
- Swagger UI: `/api/docs`
- ReDoc: `/api/redoc`

The main preparation and research commands are:

```text
POST /api/v1/collections/{collection_id}/documents
POST /api/v1/collections/{collection_id}/documents/{document_id}/preparation
POST /api/v1/collections/{collection_id}/objective-discovery
POST /api/v1/collections/{collection_id}/objectives/{objective_id}/analysis
```

Objective discovery and analysis both require an explicit non-empty
`document_ids` selection. Every selected Document must be ready.

## Formal Backend Docs

- [`docs/README.md`](docs/README.md): backend reading order.
- [`docs/specs/api.md`](docs/specs/api.md): public API contract.
- [`docs/architecture/overview.md`](docs/architecture/overview.md): ownership and
  runtime flow.
- [`docs/architecture/persistence-model.md`](docs/architecture/persistence-model.md):
  current identities and storage rules.
- [`docs/runbooks/backend-ops.md`](docs/runbooks/backend-ops.md): local operation.

## Local Development

```bash
cd backend
uv venv .venv && source .venv/bin/activate
uv sync

export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=qwen1.5-8b-chat
export LLM_API_KEY=sk-local
export DOCUMENT_PREPARATION_MAX_CONCURRENCY=10
export CORE_EXTRACTION_MAX_CONCURRENCY=4
export LENS_DATABASE_URL='postgresql+psycopg://lens:<password>@localhost:5432/lens-postgres-dev'

alembic upgrade head
alembic current --check-heads
uvicorn main:app --reload --port 8010
```

PostgreSQL is the maintained structured-state authority. Alembic is the only
schema authority. Do not add a runtime schema fallback or compatibility read.
