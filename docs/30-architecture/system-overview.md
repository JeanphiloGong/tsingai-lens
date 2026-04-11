# System Overview

## Purpose

TsingAI-Lens is a collection-oriented literature system for ingesting papers,
building graph, report, evidence, comparison, and conditional protocol
artifacts, and exposing those results through a browser-facing API and
frontend.

## Primary Modules

- `backend/`
  Owns ingestion, indexing orchestration, protocol extraction, graph and report
  retrieval, and the backend HTTP contract.
- `frontend/`
  Owns the browser application and same-origin interaction with the backend.
- `docs/`
  Owns shared governance, shared architecture, shared contracts, and
  non-authoritative research notes.

## Core User Flow

1. Create a collection.
2. Upload PDF or TXT files into the collection.
3. Start an index task.
4. Wait for graph, report, evidence, comparison, and conditional protocol
   artifacts.
5. Browse workspace, graph, evidence, comparison, protocol, and report outputs
   through the frontend or API.

## Current Product Direction

The current shared direction for Lens v1 is evidence-first and
comparison-first:

- evidence and comparison outputs are the primary product value
- protocol generation is a conditional branch for suitable collections
- mixed or review-heavy literature may still produce useful outputs even when
  no final protocol steps are emitted

See
[`lens-v1-architecture-boundary.md`](lens-v1-architecture-boundary.md)
for the shared boundary and object model.

## Backend Ownership Seams

- `backend/api/`
  Public query and report route boundary.
- `backend/controllers/`
  Current app-layer HTTP routes for collections, tasks, and workspace.
- `backend/application/`
  Query and report use-case orchestration.
- `backend/services/`
  Collection, task, workspace, and protocol services.
- `backend/retrieval/`
  Indexing and query engine package.
- `backend/infra/persistence/`
  Persistence adapter boundary.

## Frontend Ownership Seams

- `frontend/src/routes/+page.svelte`
  Collection list and creation entry flow.
- `frontend/src/routes/collections/`
  Collection workspace route family.
- `frontend/src/routes/_shared/`
  Shared browser-side API wrappers, route support logic, and i18n.

## Documentation Ownership Model

- Root `docs/` is shared-only.
- `backend/README.md` and `frontend/README.md` are module entry pages.
- Narrower code-owned seams may use local `README.md` files for purpose and
  navigation.
- Module-local `docs/README.md` is optional and only justified when a local
  docs subtree needs a second index.
