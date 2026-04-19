# Backend Module Overview

## Purpose

This document is the backend-wide architecture overview for the current module.

It explains the main ownership seams, the current runtime shape, and the
backend-local reading path for architecture questions. It does not own active
delivery sequencing or plan-family routing.

## Backend Role In The System

The backend turns collection material into document profile, evidence,
comparison, Core-derived graph/report, and conditional protocol artifacts and
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
  protocol, reports, documents, evidence, and comparisons
- `application/`
  Use-case orchestration layer with active business-domain packages plus some
  remaining legacy flat services
- `domain/`
  Domain models and port definitions
- `infra/`
  Runtime adapters such as persistence, ingestion, Source-owned runtime seams,
  and other external integrations
- `tests/`
  Verification layout for unit, integration, end-to-end, and load coverage

## Current Architectural Shape

The backend is still in transition, but its intended shape is already visible:

- public HTTP flows currently enter through `controllers/`
- business-domain orchestration is converging under `application/`
- some legacy flat services still remain and should keep shrinking
- the Lens v1 backbone is now
  `document_profiles -> evidence_cards -> comparison_rows -> protocol branch`
- protocol remains a conditional downstream branch rather than the default
  parsing center
- graph and reports are Core-derived secondary surfaces
- query now crosses a Source-owned runtime facade rather than importing
  GraphRAG internals from product-facing application code
- historical GraphRAG engine code is being retired rather than preserved as a
  separate active backend package

The target direction is a business-domain-oriented backend rather than a
larger flat service bag.

## Main Runtime Flow

1. collection material enters through collection and ingestion surfaces
2. indexing orchestration runs Source-side indexing/runtime preparation plus
   the Lens backbone
3. document profiling produces suitability and routing signals
4. evidence extraction produces claim-centered research objects
5. comparison generation produces the primary collection-facing workspace view
6. protocol, graph, and report surfaces derive from or sit beside that primary
   backbone

## Boundary Rules

- HTTP parsing and response shaping stay in `controllers/`
- orchestration stays in `application/`
- domain invariants stay in `domain/`
- external integrations stay in `infra/`
- route code should not bypass application-owned orchestration with ad hoc
  engine imports
- protocol should stay behind documents, evidence, and comparisons
- product graph and report semantics should stay derived from Core artifacts
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
- [`application-layer-boundary.md`](application-layer-boundary.md)
  Backend ADR for HTTP and application ownership separation
- [`../specs/api.md`](../specs/api.md)
  Public backend contract reference

## Current-State And Plan Entry

For active backend migration state, implementation sequencing, or retained plan
lineage, go back to [`../README.md`](../README.md) and start from
[`../plans/current-api-surface-migration-checklist.md`](../plans/current-api-surface-migration-checklist.md)
rather than treating this architecture page as a plan index.
