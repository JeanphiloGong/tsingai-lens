# System Overview

## Purpose

TsingAI-Lens is a collection-oriented literature intelligence system for
ingesting papers, producing document profiles, a paper-facts layer, derived
evidence cards, derived comparison rows, retained graph/report artifacts, and
conditional protocol outputs, and exposing those results through a
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
4. Wait for document profiling, paper-facts extraction, derived evidence and
   comparison views, and retained downstream artifacts to be generated.
5. Browse workspace, single-paper facts, evidence, comparison, graph,
   protocol, and report outputs through the frontend or API.

## Current Product Direction

The current shared direction for Lens v1 is evidence-first and
comparison-first:

- evidence and comparison outputs are the primary product value
- those outputs should be backed by a first-class paper-facts layer rather
  than by cards alone
- protocol generation is a conditional branch for suitable collections
- mixed or review-heavy literature may still produce useful outputs even when
  no final protocol steps are emitted

See
[`../architecture/lens-v1-architecture-boundary.md`](../architecture/lens-v1-architecture-boundary.md)
for the shared boundary and object model.

## Backend Ownership Seams

- `backend/controllers/`
  Current HTTP route surface for collections, tasks, workspace, graph,
  protocol, and reports.
- `backend/application/`
  Use-case orchestration layer with active business-domain packages for
  collections, indexing, workspace, documents, evidence, comparisons, and
  protocol, plus some remaining legacy flat services.
- `backend/domain/`
  Domain models and port definitions.
- `backend/retrieval/`
  Indexing engine package plus remaining Source-internal runtime code.
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
