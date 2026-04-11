# Current API Surface Migration Checklist

## Purpose

This document records the current backend API migration state for the Lens v1
evidence-first backbone.

It exists to answer:

- which backend API surfaces already run on the new backbone
- which surfaces are still mixed or legacy
- what migration work remains
- what order should be used next

This is a backend-local current-state and execution checklist. It is not the
authoritative public API contract and it does not redefine the target backend
architecture.

## Scope

This checklist covers backend-owned HTTP surfaces under `/api/v1/*` and their
effective implementation status inside `backend/`.

It does not attempt to restate frontend requirements in full and it does not
replace:

- [`../specs/api.md`](../specs/api.md)
- [`../architecture/domain-architecture.md`](../architecture/domain-architecture.md)
- [`v1-api-migration-notes.md`](v1-api-migration-notes.md)

## Status Summary

The backend is currently in a mixed migration state.

The Lens v1 core collection workflow is now backed by the new
evidence-first/comparison-first implementation:

1. indexing task runs
2. `document_profiles` are generated
3. `evidence_cards` are generated
4. `comparison_rows` are generated
5. `protocol` remains a conditional downstream branch

However, not every public backend interface has been migrated to that same
shape. Some secondary surfaces still use older graph/report/query flows.

## Current Surface Map

### Migrated to the new Lens v1 backbone

- `POST /api/v1/collections/{collection_id}/tasks/index`
  Uses the new indexing orchestration sequence:
  `document_profiles -> evidence_cards -> comparison_rows -> protocol branch`.
- `GET /api/v1/collections/{collection_id}/workspace`
  Uses the new collection-facing workspace aggregation.
- `GET /api/v1/collections/{collection_id}/documents/profiles`
  Uses the real `DocumentProfileService`.
- `GET /api/v1/collections/{collection_id}/evidence/cards`
  Uses the real `EvidenceCardService`.
- `GET /api/v1/collections/{collection_id}/comparisons`
  Uses the real `ComparisonService`.

These endpoints are the current Lens v1 primary acceptance backbone.

### Real and required, but not backbone-specific

- `POST /api/v1/collections`
- `GET /api/v1/collections`
- `GET /api/v1/collections/{collection_id}`
- `DELETE /api/v1/collections/{collection_id}`
- `POST /api/v1/collections/{collection_id}/files`
- `GET /api/v1/collections/{collection_id}/files`
- `GET /api/v1/collections/{collection_id}/tasks`
- `GET /api/v1/tasks/{task_id}`
- `GET /api/v1/tasks/{task_id}/artifacts`

These endpoints are already real backend flows and should remain, but they are
supporting collection/task lifecycle surfaces rather than evidence-backbone
business artifacts.

### Partially migrated

- `GET /api/v1/collections/{collection_id}/protocol/steps`
- `GET /api/v1/collections/{collection_id}/protocol/search`
- `POST /api/v1/collections/{collection_id}/protocol/sop`

These protocol surfaces are now gated by the new backbone and only become
meaningful for protocol-suitable collections, but their data path is still
protocol-artifact-centric rather than fully rebuilt as a downstream derivation
from the evidence/comparison backbone.

### Still on retained legacy or secondary surfaces

- `GET /api/v1/collections/{collection_id}/graph`
- `GET /api/v1/collections/{collection_id}/graphml`
- `GET /api/v1/collections/{collection_id}/reports/communities`
- `GET /api/v1/collections/{collection_id}/reports/communities/{community_id}`
- `GET /api/v1/collections/{collection_id}/reports/patterns`
- `POST /api/v1/query`

These endpoints are still valid backend surfaces, but they are not yet aligned
to the new Lens v1 primary comparison workflow and should be treated as
secondary retained interfaces.

## Cross-Cutting Mixed-State Notes

### Router registration remains mixed

The FastAPI app still registers both the new Lens v1 primary surfaces and the
older graph/report/query/protocol surfaces in the same application. The system
therefore remains in a mixed migration state rather than a fully converged
backend.

### Mock mode can still short-circuit real flows

If `LENS_ENABLE_MOCK_API=1`, selected formal paths may still return
mock-backed payloads for mock collections. This is useful for frontend
iteration, but it must not be confused with full real-backend acceptance.

### Task detail is task-scoped, not collection-scoped

`GET /api/v1/tasks/{task_id}` accepts a real `task_id`, not a `collection_id`.
Collection pages that need task history should use
`GET /api/v1/collections/{collection_id}/tasks`.

## Migration Checklist

### Done

- route and artifact contracts for `workspace`
- real document profile generation and listing
- real evidence card generation and listing
- real comparison row generation and listing
- indexing orchestration reordered around the new backbone
- protocol generation skipped for protocol-unsuitable collections

### Next

- complete frontend integration against:
  `workspace -> documents/profiles -> evidence/cards -> comparisons`
- verify one real end-to-end path using a non-mock collection
- run real app-layer route verification in an environment with FastAPI
  available
- keep mock mode as a development aid, not the default acceptance path

### Later

- rebuild protocol as a true downstream branch over the new backbone
- decide whether graph becomes a pure derived view from evidence/comparison
  artifacts
- decide whether reports remain retained legacy views or become
  comparison-driven summaries
- decide whether query remains generic chat/search or becomes a
  evidence-grounded retrieval surface
- finish controller/package migration toward domain-oriented backend layout

## Recommended Execution Order

1. Finish the real frontend/backend closed loop around the Lens v1 primary
   collection workflow.
2. Verify the full real path:
   create collection, upload file, start index, poll task, open workspace,
   inspect document profiles, inspect evidence cards, inspect comparisons.
3. Stabilize app-layer HTTP verification in the proper runtime environment.
4. Continue backend code reorganization toward domain-oriented controller and
   application packages.
5. Rebuild protocol as a strict downstream branch after the backbone is stable.
6. Revisit graph, reports, and query only after the primary collection
   comparison surface is fully accepted.

## Acceptance Reminder

The primary Lens v1 acceptance surface remains the collection comparison
workflow:

- `workspace`
- `documents/profiles`
- `evidence/cards`
- `comparisons`

`protocol`, `graph`, `reports`, and `query` are not the primary acceptance
center for this migration stage.

## Related Docs

- [`../specs/api.md`](../specs/api.md)
- [`../architecture/overview.md`](../architecture/overview.md)
- [`../architecture/domain-architecture.md`](../architecture/domain-architecture.md)
- [`graph-surface-plan.md`](graph-surface-plan.md)
- [`v1-api-migration-notes.md`](v1-api-migration-notes.md)
- [`evidence-first-parsing-plan.md`](evidence-first-parsing-plan.md)
