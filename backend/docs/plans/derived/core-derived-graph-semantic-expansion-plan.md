# Core-Derived Graph Semantic Expansion Plan

## Summary

This document records the next backend-local child proposal for expanding the
lean Core-derived graph after the structure-and-drilldown cutover.

The proposal keeps `GET /api/v1/collections/{collection_id}/graph` and
`GET /api/v1/collections/{collection_id}/graph/nodes/{node_id}/neighbors`
structure-only, but broadens the graph's semantic node vocabulary with
comparison-adjacent hubs that make cross-document commonality visible.

Phase 1 adds shared nodes for:

- `material`
- `property`
- `test_condition`
- `baseline`

Phase 2 conditionally adds:

- `variant`
- `process`

This is a backend-owned derived-surface child proposal. It does not redefine
the shared Lens v1 product boundary. It records the next backend execution
shape for making the graph denser without turning graph into a detail facade.

## Why This Plan Exists

The lean graph contract fixes payload ownership and keeps graph secondary, but
the current topology is still sparse:

- `document -> evidence -> comparison`

That shape is not enough for the main review question users ask once the graph
is visible:

- are multiple documents talking about the same material
- are they comparing the same property
- are apparent differences actually driven by test condition or baseline

Right now those semantics are partly present only inside comparison labels or
comparison detail fields. They are not shared graph structure, so the frontend
cannot show convergence around one material or one property as a first-class
topology.

## Scope

This proposal covers:

- expanding graph node kinds using the existing Core graph inputs only
- adding phase-1 semantic hubs from `comparison_rows.parquet`
- defining phase-2 optional hubs whose quality must be gated before adoption
- adding canonical comparison-list filters so aggregate graph nodes can drill
  back into owned Core resources
- setting truncation and default-visibility rules so the denser graph stays
  readable
- aligning docs, tests, and frontend graph behavior with the expanded topology

This proposal does not cover:

- widening the `/graph` or `/neighbors` response shape
- reintroducing graph-owned detail bundles or graph-only item-detail routes
- adding new graph readiness prerequisites beyond the current Core graph
  artifacts
- adding `protocol_step`, `anchor`, `quote`, `section`, or raw source-snippet
  nodes to the default graph surface
- doing cross-collection entity resolution or bespoke NLP merging beyond the
  current normalized row fields
- making graph a primary Lens v1 acceptance surface

## Design Decision

The backend should adopt these rules:

1. keep `/graph`, `/graphml`, and `/neighbors` as lean structure contracts
2. expand semantics through new node kinds and edge kinds derived from
   `comparison_rows.parquet`
3. preserve provenance by attaching semantic hubs to `comparison` nodes rather
   than adding shortcut `document -> semantic hub` edges
4. send aggregate-node drilldown back to canonical `comparisons` resources,
   not to a graph-specific detail wrapper
5. stage noisier semantics behind a second wave and frontend type toggles
6. do not add adapter, facade, or compatibility layers for the graph contract

## End-State Topology

The backbone remains:

```text
document -> evidence -> comparison
```

Phase 1 expands that backbone to:

```text
document -> evidence -> comparison -> material
comparison -> property
comparison -> test_condition
comparison -> baseline
```

Phase 2, if data quality is good enough, adds:

```text
comparison -> variant -> material
comparison -> process
```

## Phase 1 Node And Edge Design

### Node Kinds

- `material`
  - source field: `material_system_normalized`
  - display label: the normalized material string already emitted by
    comparison rows
  - node id: `mat:{sha1(normalized_key)}`
- `property`
  - source field: `property_normalized`
  - display label: the normalized property string
  - node id: `prop:{sha1(normalized_key)}`
- `test_condition`
  - source field: `test_condition_normalized`
  - display label: the normalized test-condition string
  - node id: `tc:{sha1(normalized_key)}`
- `baseline`
  - source field: `baseline_normalized`
  - display label: the normalized baseline string
  - node id: `base:{sha1(normalized_key)}`

### Edge Kinds

- keep `document_to_evidence`
- keep `evidence_to_comparison`
- add `comparison_to_material`
- add `comparison_to_property`
- add `comparison_to_test_condition`
- add `comparison_to_baseline`

### Node Normalization Rules

For stable deduplication:

- trim leading and trailing whitespace
- collapse repeated internal whitespace to single spaces
- lowercase only for the hash key, not for the display label
- reuse the comparison-row field as the display label after whitespace cleanup

The projection must not create phase-1 semantic nodes for placeholder values:

- empty string
- `--`
- `unknown`
- `unspecified material system`
- `unspecified test condition`
- `unspecified baseline`

`property_normalized = qualitative` should remain allowed in phase 1 because it
still expresses a stable result family, but the frontend should be able to hide
property nodes when that family becomes too noisy in one collection.

### Provenance Guardrail

Do not add `document_to_material` in phase 1.

Why:

- it collapses the evidence/comparison provenance chain
- it makes material presence look direct even when it is inferred through one
  normalized comparison row
- it duplicates information already preserved by
  `document -> evidence -> comparison -> material`

## Phase 2 Optional Node And Edge Design

Phase 2 should ship only after field quality is verified on real collections.

### Optional Node Kinds

- `variant`
  - source fields: `variant_id`, `variant_label`
  - preferred id: `var:{variant_id}` when `variant_id` exists
  - fallback id: `varlbl:{sha1(normalized_label)}`
- `process`
  - source field: `process_normalized`
  - node id: `proc:{sha1(normalized_key)}`

### Optional Edge Kinds

- `comparison_to_variant`
- `variant_to_material`
- `comparison_to_process`

### Phase 2 Quality Gate

Do not enable phase 2 until these checks pass:

- `variant_label` does not explode into low-signal one-off nodes on a typical
  collection
- `process_normalized` is not dominated by placeholder strings such as
  `unspecified process`
- the added nodes improve graph interpretation more than they increase clutter

If the gate fails, phase 2 should remain off without blocking phase 1.

## Contract And Drilldown Rules

### Graph Shape

`/graph`, `/graphml`, and `/neighbors` keep the same lean shape:

- node fields remain `id / label / type / degree`
- edge fields remain `id / source / target / weight / edge_description`

The change is semantic breadth, not payload breadth.

### Canonical Drilldown

Aggregate semantic nodes must not introduce a new graph detail endpoint.

Instead:

- clicking a `material` node should route to the comparisons list filtered by
  `material_system_normalized`
- clicking a `property` node should route to the comparisons list filtered by
  `property_normalized`
- clicking a `test_condition` node should route to the comparisons list
  filtered by `test_condition_normalized`
- clicking a `baseline` node should route to the comparisons list filtered by
  `baseline_normalized`

Selected comparison rows should continue to use the canonical comparison-item
endpoint defined by the structure-and-drilldown plan.

### Comparison Filter Additions

Add the following optional filters to
`GET /api/v1/collections/{collection_id}/comparisons`:

- `material_system_normalized`
- `property_normalized`
- `test_condition_normalized`
- `baseline_normalized`

Phase 2 can later add:

- `variant_label`
- `process_normalized`

These filters are the canonical drilldown path for aggregate graph nodes. They
should be implemented on the owned comparisons resource, not behind a graph
wrapper.

## Truncation And Visibility Rules

Adding semantic hubs increases the risk that high-degree aggregate nodes take
over the graph when `max_nodes` is small.

The projection should therefore change truncation from a single flat ordering
to a backbone-first strategy:

1. build the full graph projection
2. select `document`, `evidence`, and `comparison` nodes first, ordered by
   degree within the backbone set
3. reserve at least 60 percent of the truncated budget for the backbone set
4. fill the remaining budget with semantic hub nodes that are adjacent to the
   selected comparison nodes
5. recompute degrees after truncation

This preserves the review path while still making shared hubs visible.

Frontend default visibility should be:

- on by default: `document`, `evidence`, `comparison`, `material`, `property`
- off by default but toggleable: `test_condition`, `baseline`
- phase 2 defaults off until quality is proven: `variant`, `process`

## Implementation Slices

### Slice 1: Phase 1 Projection Expansion

Primary files:

- `backend/application/derived/graph_projection_service.py`
- `backend/application/derived/graph_service.py`
- `backend/controllers/schemas/derived/graph.py`
- `backend/controllers/derived/graph.py`
- `backend/infra/derived/graph/graphml.py`

Changes:

- add phase-1 semantic node construction from `comparison_rows.parquet`
- add phase-1 semantic edge construction from comparison nodes
- keep the lean graph response schema unchanged
- ensure GraphML mirrors the expanded node and edge semantics without growing
  the field set

Exit criteria:

- `/graph` returns shared material/property/test_condition/baseline nodes when
  the backing comparison fields are present
- `/neighbors` and `/graphml` reflect the same topology

### Slice 2: Canonical Comparison Drilldown Filters

Primary files:

- `backend/controllers/core/comparisons.py`
- `backend/application/core/comparison_service.py`
- `backend/controllers/schemas/core/comparisons.py`
- `backend/docs/specs/api.md`

Changes:

- add the phase-1 comparison-list filters
- keep `GET /comparisons/{row_id}` as the item-detail drilldown route
- document that aggregate graph nodes drill down through filtered comparisons

Exit criteria:

- the frontend can open a material/property/test_condition/baseline view
  without needing any graph-only detail endpoint

### Slice 3: Frontend Semantic Graph Consumption

Primary files:

- `frontend/src/routes/_shared/graph.ts`
- `frontend/src/routes/_shared/comparisons.ts`
- `frontend/src/routes/collections/[id]/graph/+page.svelte`
- `frontend/docs/frontend-plan.md`

Changes:

- add styles and legend entries for the new node kinds
- add node-type visibility toggles
- route aggregate-node clicks to filtered comparisons
- keep document/evidence/comparison detail loading on canonical owned routes

Exit criteria:

- the graph page makes cross-document convergence visible
- the graph page still treats graph as a secondary surface rather than a
  contract owner for detail payloads

### Slice 4: Phase 2 Quality Gate And Optional Expansion

Primary files:

- `backend/application/derived/graph_projection_service.py`
- `backend/application/core/comparison_service.py`
- frontend graph route files if phase 2 is enabled

Changes:

- evaluate `variant` and `process` node quality on representative collections
- enable phase 2 only if the data-quality gate passes
- keep the wave separately switchable from phase 1 during rollout

Exit criteria:

- phase 2 ships only when it improves interpretability without dominating the
  graph

## Verification

Required verification after implementation:

- graph unit tests assert phase-1 node kinds and edge kinds
- graph tests assert placeholder values do not create semantic nodes
- truncation tests assert backbone nodes remain represented when the graph is
  cut down
- comparisons list tests cover the new filter parameters
- frontend graph checks cover type toggles and aggregate-node drilldown
- `python3 scripts/check_docs_governance.py`

## Related Docs

- [`core-derived-graph-follow-up-plan.md`](core-derived-graph-follow-up-plan.md)
- [`core-derived-graph-structure-and-drilldown-plan.md`](core-derived-graph-structure-and-drilldown-plan.md)
- [`core-derived-graph-cutover-implementation-plan.md`](core-derived-graph-cutover-implementation-plan.md)
- [`../../specs/api.md`](../../specs/api.md)
- [`../../../../frontend/docs/frontend-plan.md`](../../../../frontend/docs/frontend-plan.md)
