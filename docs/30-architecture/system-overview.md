# System Overview

## Purpose

TsingAI-Lens is a collection-oriented literature system for ingesting papers,
building graph and protocol artifacts, and exposing those results through a
browser-facing API and frontend.

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
4. Wait for graph, protocol, and report artifacts.
5. Browse workspace, graph, protocol, and report outputs through the frontend
   or API.

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
