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
  Current HTTP route surface grouped as `goal/`, `source/`, `core/`, and
  `derived/`.
- `application/`
  Use-case orchestration layer grouped as `goal/`, `source/`, `core/`, and
  `derived/`.
- `domain/`
  Domain models and port definitions.
- `infra/`
  Persistence, Source runtime, ingestion, and other infrastructure adapters.
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

Operations:

- [`docs/runbooks/backend-ops.md`](docs/runbooks/backend-ops.md)
  Local development and operations runbook
- [`docs/plans/README.md`](docs/plans/README.md)
  Backend plan-family landing page for active waves and retained lineage

If you are already inside an active backend change wave, use
[`docs/plans/backend-wide/current-api-surface-migration-checklist.md`](docs/plans/backend-wide/current-api-surface-migration-checklist.md)
as the current-state page, then choose the owning plan family from
[`docs/plans/README.md`](docs/plans/README.md) rather than starting from a
flat file list.

## Code-Owned Entry Pages

- [`docs/specs/api.md`](docs/specs/api.md)
  Public HTTP contract reference
- [`application/README.md`](application/README.md)
- [`controllers/`](controllers/)
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
export CORE_EXTRACTION_MAX_CONCURRENCY=4

uvicorn main:app --reload --port 8010
```

## Notes

- The current Lens v1 backbone order is
  `document_profiles -> paper facts family -> comparison_rows /
  evidence_cards -> protocol branch`.
- Collection-facing `/api/v1/*` surfaces are currently hosted through
  `controllers/source/*`, `controllers/core/*`, `controllers/derived/*`, and
  `controllers/goal/*`.
- `backend/docs/specs/api.md` is the authoritative backend contract for
  frontend integration.
- Run backend tests with `uv run pytest` or `./.venv/bin/python -m pytest` so
  the backend-local FastAPI/test dependencies are available during verification.
- `CORE_EXTRACTION_MAX_CONCURRENCY` is an optional Core extraction tuning knob;
  when unset, the backend uses `4`.
- The active backend cleanup direction is to keep the
  `goal / source / core / derived` split explicit in `controllers/`,
  `application/`, and `infra/`, keep Source runtime under `infra/source/*`,
  and keep protocol behind the evidence/comparison backbone.
- Public protocol browsing is collection-scoped under
  `/api/v1/collections/{collection_id}/protocol/*`.
- Use `python3 ../scripts/check_docs_governance.py` when changing governed docs
  or node-local module entry pages.
