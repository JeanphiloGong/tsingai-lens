# TsingAI-Lens Backend

FastAPI backend for collection ingestion, indexing, graph/report browsing, protocol extraction, and query.

## Module Purpose

The backend owns collection-oriented ingestion, indexing orchestration,
protocol extraction, report retrieval, and the browser-facing API contract.

This file is the backend module entry page. Formal backend source-of-truth docs
live in `backend/docs/`. Narrower ownership seams use local `README.md` files
next to code.

## Ownership Map

- `api/`
  Public HTTP route boundary for query and reports.
- `controllers/`
  App-layer HTTP surface for collections, tasks, and workspace routes during
  the current migration.
- `application/`
  Use-case orchestration for query and report flows.
- `services/`
  Collection, task, workspace, and protocol services used by the app layer.
- `retrieval/`
  Indexing and query engine package.
- `infra/persistence/`
  Persistence adapter selection and implementations.
- `tests/`
  Backend test entry and boundary layout.

## Public HTTP Contract

- Business APIs: `/api/v1/*`
- Docs/OpenAPI/Static: `/api/*`
  - `/api/docs`
  - `/api/redoc`
  - `/api/openapi.json`
  - `/api/static/*`

## Formal Backend Docs

- [`docs/api.md`](docs/api.md)
  Authoritative backend public API contract
- [`docs/backend-overview.md`](docs/backend-overview.md)
  Backend architecture overview and ownership seams
- [`docs/backend-evidence-first-parsing-plan.md`](docs/backend-evidence-first-parsing-plan.md)
  Draft backend-local implementation plan for evidence-first parsing and
  conditional protocol generation
- [`docs/backend-ops.md`](docs/backend-ops.md)
  Local development and operations runbook
- [`docs/backend-application-layer-boundary.md`](docs/backend-application-layer-boundary.md)
  Backend ADR for the intended application-boundary direction

## Submodule Entry Pages

- [`api/README.md`](api/README.md)
- [`application/README.md`](application/README.md)
- [`retrieval/README.md`](retrieval/README.md)
- [`infra/persistence/README.md`](infra/persistence/README.md)
- [`tests/README.md`](tests/README.md)

## Local Development

```bash
cd backend
uv venv .venv && source .venv/bin/activate
uv sync

export LLM_BASE_URL=http://localhost:11434/v1
export LLM_MODEL=qwen1.5-8b-chat
export LLM_API_KEY=sk-local

uvicorn main:app --reload --port 8010
```

## Notes

- Public query and reports routes live under `api/routes/*`.
- Collection, task, workspace, graph, and protocol routes are currently exposed
  through `controllers/*`.
- Public protocol browsing is collection-scoped under
  `/api/v1/collections/{collection_id}/protocol/*`.
- Use `python3 ../scripts/check_docs_governance.py` when changing governed docs
  or node-local module entry pages.
