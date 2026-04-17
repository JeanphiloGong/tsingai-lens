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

It supersedes [`v1-api-migration-notes.md`](v1-api-migration-notes.md) as the
current migration entry point while that note is retained as historical bridge
context.

## Status Summary

The backend product surface is now mostly converged on the Core-first shape.

The Lens v1 core collection workflow is now backed by the new
evidence-first/comparison-first implementation:

1. indexing task runs
2. `document_profiles` are generated
3. `evidence_cards` are generated
4. `comparison_rows` are generated
5. `protocol` remains a conditional downstream branch

Graph and report surfaces now consume the same Core artifacts as derived
secondary views. The main remaining mixed area is Source-internal GraphRAG
generation/runtime ownership plus a few compatibility route names that still
carry old `community_*` vocabulary.

## Current Surface Map

### Primary surfaces on the new Lens v1 backbone

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

### Core-derived secondary surfaces

- `GET /api/v1/collections/{collection_id}/graph`
  Now projects graph payloads from
  `document_profiles/evidence_cards/comparison_rows`.
- `GET /api/v1/collections/{collection_id}/graphml`
  Exports the same Core-derived graph projection.
- `GET /api/v1/collections/{collection_id}/reports/communities`
  Remains a compatibility route name, but now lists Core-derived pattern
  groups rather than GraphRAG community reports.
- `GET /api/v1/collections/{collection_id}/reports/communities/{community_id}`
  Returns Core-derived pattern-group detail payloads.
- `GET /api/v1/collections/{collection_id}/reports/patterns`
  Exposes the same Core-derived report family with more direct naming.

These endpoints are not primary acceptance surfaces, but they are no longer
legacy product semantics either.

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

## Cross-Cutting Mixed-State Notes

### Public routes are more converged than internal runtimes

The FastAPI app still exposes primary surfaces together with protocol, graph,
and reports in one application. That no longer means graph/report are legacy.
The remaining mixed state is mostly internal:

- some report route names still carry compatibility `community_*` vocabulary
- protocol remains a downstream conditional branch rather than a fully rebuilt
  Core-native derivative
- Source may still retain GraphRAG-shaped generation/runtime code internally

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
- graph product surface cut over to Core-derived projection
- report product surface cut over to Core-derived pattern grouping
- workspace graph readiness cut over to Core inputs
- public task vocabulary cut over from `graphrag_*` to `source_index_*`
- public query surface and app/source query runtime retired
- authority docs aligned to the current Core-first graph/report/task wording

### Next

- add contract guard tests for Core-first graph/report/readiness/task semantics
- run real app-layer route verification in an environment with FastAPI
  available

### Later

- rebuild protocol as a true downstream branch over the new backbone
- decide how far Source-internal GraphRAG artifact generation should be
  retained, made lazy, or retired
- finish controller/package migration toward domain-oriented backend layout

## Recommended Execution Order

1. Add regression guards for graph/report/readiness/task vocabulary drift.
2. Verify the full real path:
   create collection, upload file, start index, poll task, open workspace,
   inspect document profiles, inspect evidence cards, inspect comparisons.
3. Stabilize app-layer HTTP verification in the proper runtime environment.
4. Continue backend code reorganization toward domain-oriented controller and
   application packages.
5. Rebuild protocol as a strict downstream branch after the backbone is stable.
6. Make an explicit Source-internal decision on legacy GraphRAG artifact
   generation.

## Acceptance Reminder

The primary Lens v1 acceptance surface remains the collection comparison
workflow:

- `workspace`
- `documents/profiles`
- `evidence/cards`
- `comparisons`

`protocol`, `graph`, and `reports` are not the primary acceptance center for
this migration stage, but `graph` and `reports` now already consume Core
artifacts rather than defining a competing product fact model.

## Related Docs

- [`../specs/api.md`](../specs/api.md)
- [`../architecture/overview.md`](../architecture/overview.md)
- [`../architecture/domain-architecture.md`](../architecture/domain-architecture.md)
- [`core-stabilization-and-seam-extraction-plan.md`](core-stabilization-and-seam-extraction-plan.md)
- [`goal-core-source-implementation-plan.md`](goal-core-source-implementation-plan.md)
- [`graph-surface-plan.md`](graph-surface-plan.md)
- [`core-first-product-surface-cutover-plan.md`](core-first-product-surface-cutover-plan.md)
- [`v1-api-migration-notes.md`](v1-api-migration-notes.md)
- [`evidence-first-parsing-plan.md`](evidence-first-parsing-plan.md)
