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
  Use-case orchestration layer. It is currently flat and should move toward
  business-domain packaging.
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
  Authoritative backend API contract for frontend integration
- [`docs/backend-v1-api-contract.md`](docs/backend-v1-api-contract.md)
  Backend-local notes for implementing the agreed Lens v1 API contract
- [`docs/backend-domain-architecture.md`](docs/backend-domain-architecture.md)
  Target backend-local business-domain seams and package direction
- [`docs/backend-goal-core-source-layering.md`](docs/backend-goal-core-source-layering.md)
  Backend-local proposal for goal-driven entry, collection intelligence core,
  and source acquisition seams
- [`docs/backend-goal-core-source-implementation-plan.md`](docs/backend-goal-core-source-implementation-plan.md)
  Backend-local execution plan for Core hardening, protocol decoupling, goal
  contracts, and source expansion
- [`docs/backend-overview.md`](docs/backend-overview.md)
  Backend architecture overview and ownership seams
- [`docs/backend-evidence-first-parsing-plan.md`](docs/backend-evidence-first-parsing-plan.md)
  Draft backend-local implementation plan for Lens v1 evidence-first parsing
  and conditional protocol generation
- [`docs/backend-ops.md`](docs/backend-ops.md)
  Local development and operations runbook
- [`docs/backend-application-layer-boundary.md`](docs/backend-application-layer-boundary.md)
  Backend ADR for the intended application-boundary direction

## Code-Owned Entry Pages

- [`docs/api.md`](docs/api.md)
  Public HTTP contract reference
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
- The next backend-local architecture step is to freeze the collection
  comparison API contract and then reorganize `application/` by business
  domain.
- Public protocol browsing is collection-scoped under
  `/api/v1/collections/{collection_id}/protocol/*`.
- Use `python3 ../scripts/check_docs_governance.py` when changing governed docs
  or node-local module entry pages.
