# TsingAI-Lens Backend

FastAPI backend for collection ingestion, indexing orchestration, workspace
assembly, evidence/comparison browsing, graph/report browsing, conditional
protocol generation, and the browser-facing API contract.

## Module Purpose

The backend owns collection-oriented ingestion, indexing orchestration,
workspace state, artifact generation, conditional protocol extraction, report
retrieval, and the browser-facing API contract.

This file is the backend module entry page. Formal backend source-of-truth docs
live in `backend/docs/`. Narrower ownership seams use local `README.md` files
next to code.

## Ownership Map

- `controllers/`
  Current HTTP route surface for collections, tasks, workspace, graph,
  protocol, query, reports, documents, evidence, and comparisons.
- `application/`
  Use-case orchestration layer. It now contains active business-domain packages
  and still carries some legacy flat services that should keep shrinking.
- `domain/`
  Domain models and port definitions.
- `retrieval/`
  Indexing and query engine package.
- `infra/`
  Persistence and infrastructure adapters.
- `docs/`
  Backend-owned architecture, spec, plan, and runbook docs.
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

Start here:

- [`docs/README.md`](docs/README.md)
  Backend docs index with the local reading order
- [`docs/specs/api.md`](docs/specs/api.md)
  Authoritative backend API contract for frontend integration
- [`docs/architecture/overview.md`](docs/architecture/overview.md)
  Backend architecture overview and ownership seams

Current state and active plans:

- [`docs/plans/current-api-surface-migration-checklist.md`](docs/plans/current-api-surface-migration-checklist.md)
  Canonical current-state page for the active Lens v1 backend migration
- [`docs/plans/core-stabilization-and-seam-extraction-plan.md`](docs/plans/core-stabilization-and-seam-extraction-plan.md)
  Active near-term child plan for stabilizing the Core slice and extracting
  the shared parsing seam from the protocol branch
- [`docs/plans/goal-core-source-implementation-plan.md`](docs/plans/goal-core-source-implementation-plan.md)
  Broader parent roadmap for the five-layer backend rollout
- [`docs/plans/goal-core-source-contract-follow-up-plan.md`](docs/plans/goal-core-source-contract-follow-up-plan.md)
  Active child plan for Goal Brief, Source Builder, Core, Goal Consumer, and
  downstream contract freeze
- [`docs/plans/graph-surface-plan.md`](docs/plans/graph-surface-plan.md)
  Active retained-secondary-surface plan for graph hardening

Architecture background:

- [`docs/architecture/domain-architecture.md`](docs/architecture/domain-architecture.md)
  Target backend-local business-domain seams and package direction
- [`docs/architecture/goal-core-source-layering.md`](docs/architecture/goal-core-source-layering.md)
  Backend-local five-layer research architecture centered on the Core backbone
- [`docs/architecture/application-layer-boundary.md`](docs/architecture/application-layer-boundary.md)
  Backend ADR for the intended application-boundary direction

Historical background:

- [`docs/plans/evidence-first-parsing-plan.md`](docs/plans/evidence-first-parsing-plan.md)
  Origin plan for the evidence-first parsing transition, kept for lineage
- [`docs/plans/v1-api-migration-notes.md`](docs/plans/v1-api-migration-notes.md)
  Historical bridge note behind the current API migration checklist

Operations:

- [`docs/runbooks/backend-ops.md`](docs/runbooks/backend-ops.md)
  Local development and operations runbook

## Code-Owned Entry Pages

- [`docs/specs/api.md`](docs/specs/api.md)
  Public HTTP contract reference
- [`application/README.md`](application/README.md)
- [`controllers/`](controllers/)
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

- The current Lens v1 backbone order is
  `document_profiles -> evidence_cards -> comparison_rows -> protocol branch`.
- Collection-facing `/api/v1/*` surfaces are currently hosted through
  `controllers/*`.
- `backend/docs/specs/api.md` is the authoritative backend contract for
  frontend integration.
- The active backend cleanup direction is to keep shrinking legacy flat seams
  in `application/` and keep protocol behind the evidence/comparison backbone.
- Public protocol browsing is collection-scoped under
  `/api/v1/collections/{collection_id}/protocol/*`.
- Use `python3 ../scripts/check_docs_governance.py` when changing governed docs
  or node-local module entry pages.
