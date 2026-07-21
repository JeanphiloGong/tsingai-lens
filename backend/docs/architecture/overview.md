# Backend Module Overview

## Purpose

This document is the backend-wide architecture overview for the current module.

It explains the main ownership seams, the current runtime shape, and the
backend-local reading path for architecture questions. It does not own active
delivery sequencing or plan-family routing.

## Backend Role In The System

The backend turns collection material into document profiles, a paper-facts
layer, derived evidence/comparison views, Core-derived graph artifacts, and
exposes those results through the public HTTP contract.

Within the repository-wide system:

- root `docs/` owns shared product meaning, shared architecture, and
  cross-module contracts
- `backend/` owns ingestion, orchestration, storage, and the browser-facing
  API contract
- `frontend/` owns the same-origin browser experience over those backend
  surfaces

## Current Ownership Seams

- `controllers/`
  Current HTTP route surface for collections, tasks, workspace, graph,
  documents, evidence, and comparisons
- `application/`
  Use-case orchestration layer with active business-domain packages, explicit
  pipeline orchestration, and some remaining legacy flat services
- `domain/`
  Domain models and port definitions
- `infra/`
  Runtime adapters such as persistence, ingestion, Source-owned runtime seams,
  and other external integrations
- `tests/`
  Verification layout for unit, integration, end-to-end, and load coverage

## Current Architectural Shape

The backend uses the following implemented shape:

- public HTTP flows currently enter through `controllers/`
- business-domain orchestration is converging under `application/`
- remaining flat services are explicit application owners rather than hidden
  persistence composition points
- the Lens v1 semantic backbone is now
  `document_profiles -> paper facts family -> evidence_cards plus
  comparable_results / collection_comparable_results -> row projection`
- graph is a Core-derived secondary surface
- query now crosses a Source-owned runtime facade rather than importing
  GraphRAG internals from product-facing application code
- PostgreSQL owns structured runtime state, object storage owns immutable
  bytes, and local files hold only rebuildable scratch as defined in
  [`persistence-model.md`](persistence-model.md)
- no SQLite or vector database is selectable at runtime; the retained SQLite
  Source implementation supports isolated tests only
- historical GraphRAG engine code is being retired rather than preserved as a
  separate active backend package

The target direction is a business-domain-oriented backend rather than a
larger flat service bag.

## Main Runtime Flow

1. collection material enters through collection and ingestion surfaces
2. collection build pipeline orchestration runs Source-side runtime preparation
   plus the Lens backbone
3. document profiling produces coarse document-type and review-risk signals
4. paper-facts extraction produces the primary research objects
5. evidence and comparable-result generation produce the primary collection
   reading and workspace views, with comparison rows projected downstream
6. graph surfaces derive from or sit beside that primary backbone

## Boundary Rules

- HTTP parsing and response shaping stay in `controllers/`
- orchestration stays in `application/`
- domain invariants stay in `domain/`
- external integrations stay in `infra/`
- route code should not bypass application-owned orchestration with ad hoc
  engine imports
- product graph semantics should stay derived from Core artifacts
- GraphRAG should remain behind Source-owned seams rather than defining
  product-facing contracts
- shared product meaning and cross-module contracts should stay in root `docs/`

## Code-Owned Neighbors

- [`../../application/README.md`](../../application/README.md)
  Use-case orchestration boundary and domain package map
- [`../../infra/persistence/README.md`](../../infra/persistence/README.md)
  Persistence adapter boundary
- [`../../tests/README.md`](../../tests/README.md)
  Test layout and verification ownership

## Related Architecture Docs

- [`domain-architecture.md`](domain-architecture.md)
  Target backend-local business-domain seams and package direction
- [`goal-core-source-layering.md`](goal-core-source-layering.md)
  Backend-local five-layer research architecture centered on the Core backbone
- [`core-comparison/README.md`](core-comparison/README.md)
  Current comparison-semantic authority and implemented substrate
- [`application-layer-boundary.md`](application-layer-boundary.md)
  Backend ADR for HTTP and application ownership separation
- [`persistence-model.md`](persistence-model.md)
  Current and target persistence authorities, identities, build lineage, and
  deletion boundaries
- [`../specs/api.md`](../specs/api.md)
  Public backend contract reference

## Current-State And Plan Entry

For active backend migration state, implementation sequencing, or retained plan
lineage, go back to [`../README.md`](../README.md), then use
[`../plans/README.md`](../plans/README.md) and start from
[`../plans/backend-wide/api-surface-migration/current-state.md`](../plans/backend-wide/api-surface-migration/current-state.md)
rather than treating this architecture page as a flat plan index.

For the current comparison-semantic center and comparable-result substrate, use
[`core-comparison/README.md`](core-comparison/README.md) before reading
historical phase plans.
