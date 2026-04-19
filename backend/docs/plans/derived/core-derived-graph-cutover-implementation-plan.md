# Core-Derived Graph Cutover Implementation Plan

## Summary

This document records the next backend child execution plan for migrating the
collection graph from retained GraphRAG semantics to a Core-derived research
projection.

It is a detailed child plan of
[`core-derived-graph-follow-up-plan.md`](core-derived-graph-follow-up-plan.md).
The parent plan defines the direction. This child plan defines the first
implementable cutover slices.

This remains a backend-wide child plan under `docs/plans/`. It does not
justify a deeper documentation subtree yet because the work spans
`application/graph/`, graph controllers, Core artifact readers, and route
verification.

## Context

Current backend graph behavior is still centered on GraphRAG artifacts:

- `/graph` and `/graphml` currently depend on `entities.parquet` and
  `relationships.parquet`
- `community_id` filtering depends on `communities.parquet`
- `text_units.parquet` and `documents.parquet` are only used as supporting
  traceback context for those graph artifacts
- route contract is already stable at the HTTP level through
  `controllers/schemas/graph.py`

Current Core artifacts are now stable enough to support a first projection
layer:

- `document_profiles.parquet` provides document identity, type, suitability,
  and file-linked naming hints
- `evidence_cards.parquet` provides `evidence_id`, `document_id`, `claim_text`,
  `claim_type`, anchors, condition context, and traceback status
- `comparison_rows.parquet` provides `row_id`, `source_document_id`,
  `supporting_evidence_ids`, normalized property/material fields, and
  comparability status

The Source/Core seam work is now far enough along that graph can start reading
one Core-backed fact model without waiting for full search/crawler expansion.

## Scope

This child plan covers:

- a first Core-derived graph projection assembled from Core artifacts
- dual-path support so Core and legacy graph assembly can run in parallel
- GraphML export reuse over Core-derived nodes and edges
- test strategy for non-breaking migration

This child plan does not cover:

- frontend graph interaction redesign
- final graph semantic richness for all claim/condition/comparability cases
- report surface migration
- community semantics redesign in the first Core cutover slice
- removing GraphRAG graph artifacts in the first implementation wave

## Proposed Change

### Execution Goal

Add a Core-derived graph path without breaking the current graph routes.

The immediate backend outcome should be:

- Core graph assembly exists under `application/graph/`
- `/graph` can be served from Core artifacts in a dual-path mode
- `/graphml` can export the Core-derived payload
- route contract remains compatible while graph semantics change underneath

### Contract Preservation Rule

The current public graph contract should remain stable during the first
cutover wave.

That means:

- keep `GET /api/v1/collections/{collection_id}/graph`
- keep `GET /api/v1/collections/{collection_id}/graphml`
- keep `CollectionGraphResponse` as the top-level payload shape
- prefer additive payload evolution over breaking schema replacement
- avoid exposing migration-only switches in the public HTTP contract unless
  verification cannot be done internally

Recommended first implementation rule:

- add an internal assembly-mode switch in `application/graph/service.py`
- keep controller contract unchanged in the first wave

### Core Graph V0 Semantic Model

The first Core-derived graph does not need the final target graph richness yet.
It only needs a stable, traceable, collection-backed projection.

#### Node Kinds

First-pass node kinds:

- `document`
- `evidence`
- `comparison`

Recommended node IDs:

- `doc:{document_id}`
- `evi:{evidence_id}`
- `cmp:{row_id}`

#### Edge Kinds

First-pass edge kinds:

- `document_to_evidence`
- `evidence_to_comparison`

Recommended edge ID patterns:

- `edge:doc:{document_id}:evi:{evidence_id}`
- `edge:evi:{evidence_id}:cmp:{row_id}`

#### Document Node Mapping

Source artifact:

- `document_profiles.parquet`

Minimum mapping:

- `id` -> `doc:{document_id}`
- `label` -> title if present, else source filename, else document id
- `type` -> `document`
- `description` -> compact summary including `doc_type` and
  `protocol_extractable`
- `node_document_ids` -> JSON list containing the document id
- `node_document_titles` -> JSON list containing the resolved title when
  available

Recommended optional fields:

- `node_text_unit_ids` when later traceback expansion can resolve them
- `degree`, `frequency`, `x`, `y`, `community` remain `null` in the first Core
  projection unless a real meaning is available

#### Evidence Node Mapping

Source artifact:

- `evidence_cards.parquet`

Minimum mapping:

- `id` -> `evi:{evidence_id}`
- `label` -> short normalized claim text
- `type` -> `evidence`
- `description` -> compact summary including `claim_type`,
  `traceability_status`, and confidence
- `node_document_ids` -> JSON list containing the backing `document_id`
- `node_text_unit_ids` -> JSON list derived from `evidence_anchors` snippet ids
- `node_document_titles` -> resolved through document profile lookup when
  available

#### Comparison Node Mapping

Source artifact:

- `comparison_rows.parquet`

Minimum mapping:

- `id` -> `cmp:{row_id}`
- `label` -> compact display label from
  `material_system_normalized + property_normalized`
- `type` -> `comparison`
- `description` -> compact summary including `comparability_status`,
  baseline/test normalization, and value/unit when present
- `node_document_ids` -> JSON list from `source_document_id`
- `node_text_unit_ids` -> `null` in the first pass unless supporting evidence
  traceback can be lifted cleanly

### Join Strategy

The first Core graph should prefer direct artifact keys rather than heuristic
joins.

Primary joins:

- `document_profiles.document_id` -> `evidence_cards.document_id`
- `evidence_cards.evidence_id` ->
  `comparison_rows.supporting_evidence_ids[]`
- `comparison_rows.source_document_id` is allowed as a fallback context field,
  but evidence linkage should remain primary for comparison edges

Explicit non-goal for the first cut:

- do not infer graph edges from free-text similarity or GraphRAG entity titles

### Community And Layout Compatibility

Current graph route supports `community_id`, but community semantics are a
legacy GraphRAG concept.

First-wave rule:

- keep community filtering on the legacy path only
- allow Core graph payloads to return `community=null` in the first pass
- do not block Core graph assembly on `communities.parquet`

This avoids forcing a fake community model into the first Core cutover.

### Execution Slices

#### Slice 1: Freeze The V0 Core Graph Contract

Goal:

- make the first Core graph intentionally narrow and implementable

Primary changes:

- confirm the first-pass node kinds and edge kinds above
- confirm field-by-field mapping into `GraphNodeResponse` and
  `GraphEdgeResponse`
- confirm that `community` and layout coordinates may be `null` in Core mode

Exit criteria:

- one explicit V0 mapping exists and can be implemented without guessing

#### Slice 2: Build Core Projection Assembly

Goal:

- add a dedicated backend projector that reads only Core artifacts

Primary changes:

- add `application/graph/core_projection_service.py`
- read:
  - `document_profiles.parquet`
  - `evidence_cards.parquet`
  - `comparison_rows.parquet`
- emit route-compatible `nodes` and `edges`
- reuse existing JSON-list conventions used by current graph response schema

Exit criteria:

- a collection can produce a Core-derived graph payload without
  `entities.parquet` or `relationships.parquet`

#### Slice 3: Add Dual Path In Graph Service

Goal:

- support both legacy GraphRAG and Core-derived assembly in one app-layer seam

Primary changes:

- keep legacy loading in `application/graph/service.py`
- introduce an internal mode or assembler switch there
- route GraphML rendering through the same assembled payload regardless of
  source path

Recommended rule:

- do not expose a public `mode` query parameter in the first HTTP cut unless
  verification truly requires it

Exit criteria:

- graph service can assemble from either source without changing controller
  response models

#### Slice 4: Verification And Compatibility

Goal:

- prove Core assembly works before any default cutover

Primary changes:

- add dedicated unit tests for Core graph projector fixtures
- add app-layer tests proving Core graph assembly does not require GraphRAG
  entity artifacts
- keep existing legacy integration tests intact
- verify GraphML export works over Core-assembled payloads

Exit criteria:

- Core and legacy graph paths can both be verified in tests

#### Slice 5: Default Cutover Gate

Goal:

- define what must be true before `/graph` defaults to Core semantics

Cutover gate:

- Core projector is stable on real collection fixtures
- traceback coverage is not worse than legacy in the cases we care about
- controller contract remains stable
- workspace/readiness semantics are ready to stop using
  `entities.parquet` / `relationships.parquet` as the primary graph source

Explicit non-goal:

- do not change `graph_ready` semantics in the first implementation slice

## File Change Plan

### Primary Code Areas

- new `application/graph/core_projection_service.py`
- `application/graph/service.py`
- `controllers/graph.py`
- `controllers/schemas/graph.py`

### Compatibility And Supporting Areas

- `application/workspace/artifact_registry_service.py`
- `controllers/schemas/workspace.py`
- `controllers/schemas/task.py`

These should only change when the cutover gate is reached, not in the first
projector slice.

### Tests

- new `tests/unit/services/test_graph_core_projection.py`
- `tests/unit/routers/test_graph_api.py`
- `tests/integration/test_app_layer_api.py`

## Verification

### Core Projection Verification

- Core projector can assemble a graph using only:
  - `document_profiles.parquet`
  - `evidence_cards.parquet`
  - `comparison_rows.parquet`
- payload preserves route-compatible node and edge fields
- payload carries traceback-friendly document and text-unit references where
  available

### Compatibility Verification

- existing legacy graph integration tests still pass
- controller error contracts stay stable
- GraphML export still renders valid bytes from the assembled payload

### Migration Verification

- Core graph path does not require `entities.parquet` or `relationships.parquet`
- legacy graph path still works while default cutover is deferred

## Risks And Guardrails

- If the first Core graph tries to model final graph richness too early, the
  cutover will stall. Keep the first graph to `document`, `evidence`, and
  `comparison` nodes only.
- If community semantics are forced into the first Core path, the migration
  will stay accidentally coupled to GraphRAG concepts. Keep community
  compatibility as a later problem.
- If readiness is cut over too early, workspace and task surfaces will drift
  from actual route behavior. Keep readiness semantics legacy-based until the
  dual path is stable.
- If Core graph edges are built from heuristics instead of stable keys,
  traceback trust will regress. Prefer artifact IDs and explicit joins only.

## Outcome Target

After this child plan's first implementation wave:

- backend has one real Core-derived graph assembler
- `/graph` and `/graphml` can be served from Core payloads without breaking the
  current route contract
- legacy GraphRAG graph assembly still exists as a compatibility path
- the system is ready for a controlled semantic cutover rather than a forced
  big-bang rewrite
