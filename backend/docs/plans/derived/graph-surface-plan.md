# Graph Secondary Surface Plan

## Purpose

This document records the backend-local execution plan for the retained
collection graph surfaces during the current Lens v1 migration stage.

It exists to answer:

- what status `graph` currently has in the backend
- what "done" means for `graph` in the current migration stage
- what should be hardened now versus deferred until later

This is a backend-local implementation plan. It is not the authoritative public
API contract and it does not redefine the target Lens v1 product architecture.

## Scope

This plan covers:

- `GET /api/v1/collections/{collection_id}/graph`
- `GET /api/v1/collections/{collection_id}/graphml`
- collection and task readiness fields related to graph availability
- mock and test behavior for the graph secondary surface

This plan does not:

- make `graph` part of the primary Lens v1 acceptance backbone
- replace the current comparison-first primary workflow
- force an immediate redesign of graph as a derived view over
  `document_profiles`, `evidence_cards`, and `comparison_rows`

## Current State

The current backend keeps graph as a retained secondary surface rather than a
primary Lens v1 backbone resource.

- route ownership remains in `controllers/graph.py`
- application behavior remains in `application/graph/service.py`
- data is loaded from existing GraphRAG-oriented output artifacts such as
  `entities.parquet`, `relationships.parquet`, `communities.parquet`,
  `text_units.parquet`, and `documents.parquet`
- workspace and task readiness payloads already expose `graph_ready` and
  `graphml_ready`
- the public graph routes are available in real flows and already have a happy
  path integration test

However, the surface is not yet fully hardened as a stable retained interface:

- dedicated response schemas already exist in `controllers/schemas/graph.py`,
  but the GraphML binary contract is still only implicit
- controller-level stable error payloads already exist for collection missing,
  graph not ready, and community not found cases, but
  `application/graph/service.py` still translates some lower-level
  `HTTPException` cases instead of owning the boundary completely
- mock-mode readiness flags exist, but mock route parity is still incomplete
  compared with `workspace`, `documents/profiles`, `evidence/cards`, and
  `comparisons`
- boundary and packaging cleanup is unfinished, and the compatibility shim
  `application/graph_service.py` still exists

## Decision

The recommended backend decision for the current migration stage is:

1. keep `graph` as a retained secondary surface
2. do not rebuild `graph` around comparison artifacts yet
3. harden the current graph routes so they are stable, testable, and explicit
4. revisit whether `graph` should become a pure derived view only after the
   primary collection workflow is fully accepted

This matches the current backend-local docs direction:

- the primary acceptance backbone remains
  `workspace -> documents/profiles -> evidence/cards -> comparisons`
- `graph` and `reports` remain retained secondary surfaces for now

## Current-Stage Definition of Done

For the current migration stage, `graph` should be considered done only when:

- the existing public graph paths remain unchanged and usable
- graph availability is clearly gated by stable readiness behavior
- graph and graphml responses have explicit response models
- missing, not-ready, and invalid-community cases return stable app-layer error
  payloads
- mock collections can exercise graph behavior in a way that is consistent with
  the rest of the Lens v1 frontend integration flow
- automated tests cover both success and failure contracts
- backend docs consistently describe `graph` as a retained secondary surface

This definition of done does not require `graph` to become a primary business
artifact or a comparison-driven derived view yet.

## Phase 1: Harden the Retained Surface

### Contract Hardening

Keep the graph controller contract explicit and finish the remaining binary and
documentation hardening work.

Recommended deliverables:

- `controllers/schemas/graph.py` as the stable response-model home
- response models for graph node, edge, and collection graph payloads
- explicit response model or documented binary contract for graphml export

Recommended rule:

- preserve existing route paths and query parameters

Proposed minimum stable error set:

- `404` when the collection does not exist
- `409` with stable code such as `graph_not_ready` when the collection exists
  but graph artifacts are not ready
- `404` with stable code such as `community_not_found` when a requested
  community filter does not resolve

The exact error codes should be finalized in controller-level behavior and then
reflected into `docs/specs/api.md` if the contract is made formal.

### Application-Layer Error Ownership

Finish moving graph-specific availability and filtering decisions into
`application/graph/service.py` rather than relying on lower-level
`HTTPException` shaping from `infra/graphrag/graphml_export.py`.

Recommended deliverables:

- graph-specific application exceptions for not-ready or invalid-filter cases
- controller translation from application exceptions into stable HTTP payloads
- retention of low-level storage read helpers in infra without letting them
  define the public route contract

This keeps graph behavior aligned with the newer application-layer pattern used
by `documents`, `evidence`, and `comparisons`.

### Mock Mode Parity

Bring graph behavior to the same mock boundary used by the primary Lens v1
collection surfaces.

Recommended deliverables:

- add graph payload support to `application/mock/lens_v1_service.py`
- let mock collections return graph and graphml behavior through the controller
- keep graph mock data intentionally small and deterministic

If mock parity is intentionally rejected, that decision should be written down
explicitly. Silent inconsistency is the worst outcome here.

### Verification and Tests

Preserve the existing route coverage and fill the remaining gaps.

Required coverage:

- graph happy path on a real collection fixture
- graphml export happy path
- missing collection
- graph artifacts not ready
- invalid `community_id`
- mock collection graph response

Nice-to-have coverage:

- max-node truncation behavior
- min-weight filtering behavior
- workspace capability alignment with graph availability

### Documentation Alignment

Keep backend docs aligned around one message:

- `graph` is valid and supported
- `graph` is not the primary Lens v1 acceptance surface
- the current-stage work is contract hardening, not a semantic redesign

Update at least:

- `docs/README.md`
- `docs/plans/current-api-surface-migration-checklist.md`
- `docs/specs/api.md` if any graph error or payload contract becomes explicit

## Phase 2: Derived-View Decision Gate

Phase 2 should not start until the primary Lens v1 collection workflow is
accepted end-to-end on real collections.

Entry conditions:

- the real collection workflow is stable for
  `workspace -> documents/profiles -> evidence/cards -> comparisons`
- app-layer route verification is stable
- frontend integration no longer depends on graph as a surrogate acceptance path

Decision questions:

- should `graph` remain an independent GraphRAG-oriented browsing surface
- should `graph` become a pure derived view from evidence/comparison artifacts
- should graph readiness remain tied to graph artifacts or collapse onto
  comparison readiness
- should community filtering remain part of the public graph contract if graph
  becomes comparison-driven
- should GraphML export remain supported if graph stops mirroring GraphRAG
  storage directly

Expected output of Phase 2:

- either an explicit decision to retain the current independent graph path
- or a follow-up migration plan that redesigns graph as a derived surface
  (`core-derived-graph-follow-up-plan.md`)

## Recommended Execution Order

1. Freeze the current decision that graph remains a retained secondary surface
   for this stage.
2. Add graph response schemas and stable controller-level error behavior.
3. Add mock parity or explicitly document the decision not to provide it.
4. Expand automated test coverage for graph success and failure contracts.
5. Update docs so graph status is described consistently across backend-local
   documents.
6. Revisit the derived-view question only after the primary Lens v1 comparison
   workflow is accepted.

## Non-Goals

- changing the public graph route paths in the current stage
- making graph the primary frontend acceptance surface
- rewriting graph around comparison artifacts before the primary workflow is
  stable
- removing GraphRAG-oriented graph outputs from the backend during current
  migration work

## Open Questions

- Should `graph_not_ready` mean missing `entities.parquet` and
  `relationships.parquet` only, or should it also consider missing auxiliary
  artifacts needed for community filtering?
- Should `graphml_ready` continue to mean "artifact file exists" even though the
  current graphml route can render GraphML on demand from graph payload data?
- Should the compatibility shim `application/graph_service.py` be removed in the
  same change set as contract hardening, or only after import cleanup lands?

## Related Docs

- [`../specs/api.md`](../../specs/api.md)
- [`../architecture/overview.md`](../../architecture/overview.md)
- [`../architecture/domain-architecture.md`](../../architecture/domain-architecture.md)
- [`current-api-surface-migration-checklist.md`](../backend-wide/current-api-surface-migration-checklist.md)
- [`v1-api-migration-notes.md`](../historical/v1-api-migration-notes.md)
- [`evidence-first-parsing-plan.md`](../historical/evidence-first-parsing-plan.md)
- [`core-derived-graph-follow-up-plan.md`](core-derived-graph-follow-up-plan.md)
