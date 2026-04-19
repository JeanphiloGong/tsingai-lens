# Core-Derived Graph Structure And Drilldown Plan

## Summary

This document records the next backend-local proposal for simplifying the
Core-derived graph surface after the semantic cutover.

The proposal narrows `GET /api/v1/collections/{collection_id}/graph` to a
structure-first contract, keeps layout computation in the frontend, adds a
graph-specific neighborhood expansion endpoint, and moves node detail loading
back to canonical document, evidence, and comparison resources.

This is a backend-local child plan under the derived plan family. It does not
redefine the shared Lens v1 product boundary. It records the next execution
shape for the retained graph secondary surface.

## Why This Plan Exists

The current Core-derived graph already reads the right semantic inputs:

- `document_profiles.parquet`
- `evidence_cards.parquet`
- `comparison_rows.parquet`

However, the route contract still carries fields whose ownership is either
dead, duplicated, or misplaced:

- `x` and `y` are declared in the HTTP schema even though the backend currently
  emits `null` and the frontend computes layout locally
- `community_id` still appears in the route signature even though the
  Core-derived graph explicitly rejects it
- graph node and edge payloads still include document-title, text-unit, and
  similar detail fields that belong to canonical Core or Source resources
- the frontend graph page reads those detail fields directly, which makes the
  graph secondary surface behave like a broad detail facade instead of a
  structure view

The result is a graph contract that is wider than the graph's real job.

## Scope

This proposal covers:

- shrinking `/graph` to a structure-first response
- shrinking `/graphml` to the same structure-first field set
- removing dead graph-only fields and legacy `community_id` semantics
- adding `GET /api/v1/collections/{collection_id}/graph/nodes/{node_id}/neighbors`
  for neighborhood expansion
- adding canonical single-resource detail endpoints for graph drilldown where
  they do not already exist
- updating the frontend graph page to fetch detail lazily by node kind
- aligning tests and docs with the reduced graph contract

This proposal does not cover:

- changing the public graph route paths
- introducing a new graph rendering framework
- making graph a primary Lens v1 acceptance surface
- redesigning graph semantics beyond the current `document / evidence /
  comparison` projection
- reintroducing GraphRAG community semantics into the product graph contract

## Design Decision

The backend should adopt these rules:

1. `/graph` is a graph-structure contract, not a detail bundle
2. graph layout stays frontend-owned
3. graph-specific neighborhood expansion gets a dedicated graph endpoint
4. node detail stays on canonical owned resources
5. do not add a generic graph detail facade or wrapper layer

This preserves the current Core-first graph meaning while stopping the graph
route from becoming a mixed-responsibility payload.

## End-State Contract

### 1. Structure-Only Graph Response

`GET /api/v1/collections/{collection_id}/graph`

Keep:

- `collection_id`
- `nodes`
- `edges`
- `truncated`

Keep node fields:

- `id`
- `label`
- `type`
- `degree`

Keep edge fields:

- `id`
- `source`
- `target`
- `weight`
- `edge_description`

Keep query parameters:

- `max_nodes`
- `min_weight`

Remove top-level fields:

- `output_path`
- `community`

Remove node fields:

- `description`
- `frequency`
- `x`
- `y`
- `community`
- `node_text_unit_ids`
- `node_text_unit_count`
- `node_document_ids`
- `node_document_titles`
- `node_document_count`

Remove edge fields:

- `edge_text_unit_ids`
- `edge_text_unit_count`
- `edge_document_ids`
- `edge_document_titles`
- `edge_document_count`

Remove query parameters:

- `community_id`

Rationale:

- `id`, `label`, `type`, and `degree` are enough for graph rendering,
  filtering, and selection
- edge source, target, and relation description are enough for graph topology
  and relation labeling
- layout, traceability bundles, and document detail belong elsewhere

### 2. GraphML Mirrors The Same Structure Contract

`GET /api/v1/collections/{collection_id}/graphml`

GraphML export should mirror the same structure-first node and edge fields.

That means GraphML should no longer declare or emit:

- `x`
- `y`
- `community`
- node document/title aggregate fields
- node/edge text-unit aggregate fields

The graph export remains useful for external visualization, but it should not
carry product-only detail fields whose authority lives elsewhere.

### 3. Neighborhood Expansion Is Graph-Specific

Add:

- `GET /api/v1/collections/{collection_id}/graph/nodes/{node_id}/neighbors`

Initial rule:

- return the 1-hop neighborhood for the requested node from the Core-derived
  graph projection
- include the center node in the returned subgraph
- return the same lean node and edge field set used by `/graph`

Recommended response shape:

```json
{
  "collection_id": "col_xxx",
  "center_node_id": "evi:ev-1",
  "nodes": [],
  "edges": [],
  "truncated": false
}
```

This keeps neighborhood expansion graph-owned without turning the main graph
payload into an always-expanded structure.

### 4. Node Detail Uses Canonical Resources

The graph page should stop expecting full detail inside `/graph`.

Instead, it should fetch canonical resource detail by node kind:

- `doc:{document_id}`
  - add `GET /api/v1/collections/{collection_id}/documents/{document_id}/profile`
  - keep existing `GET /api/v1/collections/{collection_id}/documents/{document_id}/content`
    for deeper Source-backed reading
- `evi:{evidence_id}`
  - add `GET /api/v1/collections/{collection_id}/evidence/{evidence_id}`
  - keep existing `GET /api/v1/collections/{collection_id}/evidence/{evidence_id}/traceback`
    for deeper Source-backed traceback
- `cmp:{row_id}`
  - add `GET /api/v1/collections/{collection_id}/comparisons/{row_id}`

Canonical single-resource detail endpoints should be backed by the owning Core
or Source services. They should not be re-exposed through a graph-only facade.

## Rejected Option

Do not add:

- `GET /api/v1/collections/{collection_id}/graph/nodes/{node_id}/detail`

Why it is rejected:

- it would act as a wrapper over heterogeneous document, evidence, and
  comparison resources
- it would duplicate fields already owned by canonical controllers and schemas
- it would make graph responsible for detail assembly that belongs to other
  seams
- it would encourage future graph payload expansion instead of direct caller
  updates

If the frontend needs convenience, it should parse the node-id prefix and call
the owned resource directly.

## Frontend Consumption Rules

The graph page should be updated with these rules:

- compute layout in the browser only
- remove the community filter UI because `community_id` is no longer part of
  the contract
- render the graph from lean `nodes` and `edges`
- on node click, fetch detail lazily using the canonical route for that node
  kind
- on request, expand the selected node through the neighbors endpoint
- keep edge detail local to the graph payload because edge metadata stays small

This keeps the graph route secondary and lightweight while still allowing real
drilldown.

## Implementation Slices

### Slice 1: Freeze The Lean Graph Contract

Primary files:

- `backend/controllers/schemas/derived/graph.py`
- `backend/application/derived/graph_projection_service.py`
- `backend/application/derived/graph_service.py`
- `backend/controllers/derived/graph.py`
- `backend/infra/derived/graph/graphml.py`

Changes:

- remove dead and duplicated fields from the graph response schema
- remove `community_id` from the public graph and graphml route signatures
- remove `community` and `output_path` from the graph payload
- keep `max_nodes` and `min_weight`
- align GraphML export with the reduced field set

Exit criteria:

- `/graph` returns only structural graph data
- `/graphml` exports only structural graph data
- no backend graph code still assigns `x`, `y`, or community-shaped values

### Slice 2: Add Neighborhood Expansion

Primary files:

- `backend/controllers/derived/graph.py`
- `backend/application/derived/graph_service.py`
- `backend/controllers/schemas/derived/graph.py`

Changes:

- add a neighborhood response model
- add a controller route for `graph/nodes/{node_id}/neighbors`
- assemble the 1-hop subgraph directly from the Core-derived projection
- return `404` when the node id does not exist in the collection graph

Exit criteria:

- the graph page can request incremental neighborhood context without
  re-downloading the full graph every time

### Slice 3: Add Canonical Single-Resource Detail Endpoints

Primary files:

- `backend/controllers/core/documents.py`
- `backend/controllers/core/evidence.py`
- `backend/controllers/core/comparisons.py`
- `backend/controllers/schemas/core/documents.py`
- `backend/controllers/schemas/core/evidence.py`
- `backend/controllers/schemas/core/comparisons.py`
- `backend/application/core/document_profile_service.py`
- `backend/application/core/evidence_card_service.py`
- `backend/application/core/comparison_service.py`

Changes:

- add a single document profile endpoint
- add a single evidence-card endpoint
- add a single comparison-row endpoint
- keep deep Source-backed detail on the existing document content and evidence
  traceback endpoints

Exit criteria:

- each graph node kind has one canonical item-detail route
- graph node selection no longer depends on graph payload duplication

### Slice 4: Migrate Frontend Graph Drilldown

Primary files:

- `frontend/src/routes/_shared/graph.ts`
- `frontend/src/routes/_shared/documents.ts`
- `frontend/src/routes/_shared/evidence.ts`
- `frontend/src/routes/_shared/comparisons.ts`
- `frontend/src/routes/collections/[id]/graph/+page.svelte`

Changes:

- shrink the frontend graph type definitions to the lean contract
- remove community filter handling
- remove direct reliance on graph detail aggregates
- load node detail by node prefix and canonical fetcher
- add neighborhood expansion interaction

Exit criteria:

- the graph page renders from structure only
- node detail loads from canonical resources
- no frontend graph code still expects server coordinates

### Slice 5: Tests And Docs Cleanup

Primary files:

- `backend/tests/integration/test_app_layer_api.py`
- `backend/tests/unit/services/test_graph_core_projection.py`
- frontend graph-route tests if present
- `backend/docs/specs/api.md`
- this derived plan family

Changes:

- update graph contract tests to assert the lean field set
- add neighborhood endpoint coverage
- add single-resource detail endpoint coverage
- remove tests that assert dead graph fields
- update the backend API spec after the implementation lands

Exit criteria:

- no tests or docs still describe layout or community fields as live graph
  contract

## Verification

Required verification after implementation:

- `/graph` success path with lean fields only
- `/graphml` success path with lean export keys only
- `/graph/nodes/{node_id}/neighbors` success and missing-node cases
- single-resource document, evidence, and comparison detail endpoints
- frontend graph route still renders, selects nodes, and expands neighbors
- no remaining frontend code depends on `community_id`, `x`, `y`, or graph-side
  detail aggregates

## Related Docs

- [`core-derived-graph-follow-up-plan.md`](core-derived-graph-follow-up-plan.md)
- [`core-derived-graph-cutover-implementation-plan.md`](core-derived-graph-cutover-implementation-plan.md)
- [`core-derived-graph-semantic-expansion-plan.md`](core-derived-graph-semantic-expansion-plan.md)
- [`graph-surface-plan.md`](graph-surface-plan.md)
- [`../../specs/api.md`](../../specs/api.md)
- [`../../../../docs/architecture/graph-surface-current-state.md`](../../../../docs/architecture/graph-surface-current-state.md)
- [`../../../../frontend/src/routes/collections/lens-v1-interface-spec.md`](../../../../frontend/src/routes/collections/lens-v1-interface-spec.md)
