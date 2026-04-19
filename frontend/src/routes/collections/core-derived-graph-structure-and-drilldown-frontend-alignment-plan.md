# Core-Derived Graph Structure And Drilldown Frontend Alignment Plan

## Purpose

This document records the frontend-local implementation plan for adopting the
lean Core-derived graph contract on the existing collection graph surface.

The goal is to cut the current `/collections/[id]/graph` page over to the new
structure-first graph payload, lazy canonical node drilldown, and graph-owned
neighbors expansion flow without introducing a new route family or a
frontend-local compatibility facade.

## Scope

In scope:

- direct frontend adoption of the lean `/graph` response
- direct frontend adoption of the lean `/graphml` query shape
- removal of `community_id` handling from the graph page and shared client
- lazy node-detail loading from canonical document, evidence, and comparison
  endpoints
- support for `GET /graph/nodes/{node_id}/neighbors` on the existing graph page
- graph-page state updates so selection, drilldown, and expansion no longer
  depend on graph payload detail duplication
- fixture and test updates needed to avoid masking contract drift

Out of scope:

- changing the public collection graph route path
- introducing a new graph rendering framework in the same cutover
- redesigning graph semantics beyond the current `document / evidence /
  comparison` projection
- promoting graph to a primary Lens v1 acceptance surface
- adding a frontend wrapper that reconstructs the removed graph detail fields

## Companion Docs

- [`../../../../backend/docs/plans/derived/core-derived-graph-structure-and-drilldown-plan.md`](../../../../backend/docs/plans/derived/core-derived-graph-structure-and-drilldown-plan.md)
  Backend-owned source plan for the lean graph contract and canonical drilldown
- [`lens-v1-interface-spec.md`](lens-v1-interface-spec.md)
  Collection route-family interface authority for Lens v1
- [`collection-ui-restructure-proposal.md`](collection-ui-restructure-proposal.md)
  Collection route hierarchy proposal that keeps graph secondary

## Why This Needs A Separate Frontend Plan

The backend contract change is narrow in shape but broad in consumer impact.

The graph route keeps the same page URL and the same high-level product role,
but the frontend currently assumes several fields and behaviors that will no
longer exist:

- the shared graph client still declares `output_path`, `community`, `x`, `y`,
  and document/text-unit aggregate fields
- the graph page still sends `community_id`
- the graph page still reads node and edge detail directly from the graph
  payload
- the graph page still treats the graph response as both topology and detail
  source

That mismatch deserves a dedicated frontend-local child plan rather than a
silent edit to the broader collection interface spec.

## Current Frontend Mismatch

The current frontend graph surface still depends on the old contract in four
concrete places.

### 1. Shared graph client remains wide

File:

- `frontend/src/routes/_shared/graph.ts`

Current assumptions:

- `GraphNode` still includes `description`, `frequency`, `x`, `y`,
  `community`, and document/text-unit aggregate fields
- `GraphEdge` still includes document/text-unit aggregate fields
- `GraphResponse` still includes `output_path` and `community`
- `GraphQuery` still includes `communityId`

### 2. Graph page still consumes removed graph fields

File:

- `frontend/src/routes/collections/[id]/graph/+page.svelte`

Current assumptions:

- the page keeps `communityId` local state and sends it on load and export
- node selection reads `description`, `frequency`, `community`,
  `node_document_count`, `node_text_unit_count`, and `node_document_titles`
- edge selection reads `edge_document_count`, `edge_text_unit_count`, and
  `edge_document_titles`
- graph metadata still expects `community`
- the page still contains a community filter UI

### 3. Drilldown does not yet use canonical single-resource fetches

Files:

- `frontend/src/routes/_shared/documents.ts`
- `frontend/src/routes/_shared/evidence.ts`
- `frontend/src/routes/_shared/comparisons.ts`

Current assumptions:

- documents expose collection list and content fetches, but not single-profile
  fetch
- evidence exposes collection list and traceback fetches, but not single-card
  fetch
- comparisons expose collection list fetches, but not single-row fetch

### 4. Graph page state is not ready for incremental expansion

Current assumptions:

- the rendered graph is the only effective graph state
- node detail is derived from renderer attributes instead of a separate detail
  state machine
- there is no local merge path for neighbor subgraphs

That state model is workable for a one-shot payload, but it is the wrong shape
for lazy drilldown plus neighborhood expansion.

## Frontend Adoption Rules

- keep the existing `/collections/[id]/graph` route
- directly adopt the lean `/graph` payload instead of reconstructing the old
  detail shape
- compute layout in the browser only
- remove `community_id` handling completely in the same cutover
- treat graph payload as structure data only
- fetch node detail lazily by node-id prefix and canonical resource owner
- keep edge detail local to the graph payload because edge metadata remains
  small
- merge neighborhood expansion results into a frontend-owned graph state rather
  than forcing a full reload for each drilldown step
- do not couple this contract cutover to a rendering-framework replacement

## Target Frontend Contract

The shared graph client should move to these frontend-facing types:

```ts
type GraphNode = {
  id: string;
  label: string;
  type?: string | null;
  degree?: number | null;
};

type GraphEdge = {
  id: string;
  source: string;
  target: string;
  weight?: number | null;
  edge_description?: string | null;
};

type GraphResponse = {
  collection_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
};

type GraphNeighborsResponse = {
  collection_id: string;
  center_node_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
};
```

The graph page should also introduce a frontend-local node-id discriminator:

```ts
type GraphNodeRef =
  | { kind: 'document'; resourceId: string }
  | { kind: 'evidence'; resourceId: string }
  | { kind: 'comparison'; resourceId: string }
  | { kind: 'unknown'; resourceId: string };
```

This parser should be local to the shared graph helper layer so the page does
not repeat prefix parsing logic.

## Page Interaction Model After Cutover

### Initial graph load

- load `/graph` with `max_nodes` and `min_weight` only
- store the response in a frontend-owned `graphData` state
- render the graph from that structure-only state
- keep `truncated` as a page-level status badge

### Node selection

- selecting a node should immediately show structural summary fields:
  `label`, `type`, `degree`, and node id
- the page should then lazily fetch canonical detail based on node prefix
- detail loading should have explicit `idle / loading / ready / error` state
- stale detail responses should not overwrite a newly selected node

### Edge selection

- selecting an edge should remain local to the graph payload
- edge detail should show source label, target label, weight, and
  `edge_description`
- edge detail should no longer expect document or text-unit aggregates

### Neighborhood expansion

- the page should expose an explicit user action to expand the selected node
- expansion should call `/graph/nodes/{node_id}/neighbors`
- returned nodes and edges should be merged into local graph state with id-based
  deduplication
- the page should preserve the current selection after merge
- the page should re-run layout after the merge

## File-Level Change Plan

### 1. Shared graph client

File:

- `frontend/src/routes/_shared/graph.ts`

Changes:

- shrink `GraphNode`, `GraphEdge`, and `GraphResponse` to the lean contract
- remove `communityId` from `GraphQuery`
- stop sending `community_id` in `buildQuery()`
- add `GraphNeighborsResponse`
- add `fetchCollectionGraphNeighbors()`
- add `parseGraphNodeId()` or equivalent node-kind helper

Do not:

- preserve compatibility fields that the backend has removed
- add a frontend-local synthetic `community` concept
- rebuild old detail aggregates from canonical endpoints just to mimic the
  removed graph payload

### 2. Canonical detail fetchers

Files:

- `frontend/src/routes/_shared/documents.ts`
- `frontend/src/routes/_shared/evidence.ts`
- `frontend/src/routes/_shared/comparisons.ts`

Changes:

- add `fetchDocumentProfile(collectionId, documentId)`
- add `fetchEvidenceCard(collectionId, evidenceId)`
- add `fetchComparisonRow(collectionId, rowId)`
- keep existing content and traceback fetchers as deeper reading actions
- keep normalization local to each shared client

The graph page should import these shared fetchers rather than performing
resource-specific request logic inline.

### 3. Graph page state and loading flow

File:

- `frontend/src/routes/collections/[id]/graph/+page.svelte`

Changes:

- remove `communityId` local state and the related UI
- remove `graphMeta.community`
- replace the current `selectedNode: GraphNode` pattern with separate
  `selectedNodeSummary` and `selectedNodeDetail` state
- keep `selectedEdge` as a lean graph-local detail model
- introduce a frontend-owned `graphData` source of truth so neighbor expansion
  can merge into stable state
- stop reading node detail from renderer attributes that no longer map to the
  backend contract

### 4. Graph detail panel

File:

- `frontend/src/routes/collections/[id]/graph/+page.svelte`

Changes:

- node summary should show `label`, `type`, `degree`, and a stable id
- document drilldown should render document-profile fields
- evidence drilldown should render evidence-card fields
- comparison drilldown should render comparison-row fields
- edge detail should render only lean edge fields
- add explicit loading and error states for node detail
- add an `Expand neighbors` action in the selected-node panel

The page should stop rendering graph-side fields that no longer exist:

- `community`
- `frequency`
- `description` from graph payload
- node document aggregate fields
- node text-unit aggregate fields
- edge document aggregate fields
- edge text-unit aggregate fields

### 5. Shared copy and styling

Files:

- `frontend/src/routes/_shared/i18n.ts`
- `frontend/src/routes/layout.css`

Changes:

- remove graph copy that only exists for community or aggregate detail fields
- add copy for lazy detail loading, detail errors, and neighbor expansion
- keep the graph page secondary in tone and hierarchy
- avoid adding copy that implies graph is the canonical detail surface

### 6. Fixtures and tests

Files:

- graph-route tests if present
- shared-client tests if added in the same wave

Changes:

- update graph fixtures to the lean field set only
- add coverage for prefix-based detail fetching
- add coverage for neighbor merge behavior
- add coverage that the page no longer sends `community_id`
- remove tests that assert deleted graph fields

## Migration Sequence

1. Cut the shared graph client over to the lean transport contract.
2. Add canonical single-resource fetchers for document, evidence, and
   comparison drilldown.
3. Refactor the graph page state so structure rendering and node detail are
   separate concerns.
4. Remove community UI and deleted graph-field rendering.
5. Add neighbor expansion and local subgraph merge behavior.
6. Update fixtures, copy, and tests.

This order keeps the API-facing transport layer stable before the page starts
depending on the new drilldown model.

## Verification

Required verification after implementation:

- `/collections/[id]/graph` loads successfully using only `max_nodes` and
  `min_weight`
- GraphML export still works without `community_id`
- node selection triggers the correct canonical fetch based on `doc:`,
  `evi:`, or `cmp:` prefix
- node detail loading handles success, error, and rapid reselection cases
- edge detail renders without any deleted aggregate fields
- neighbor expansion merges new nodes and edges without duplicates
- no graph-page code still expects `community`, `x`, `y`, or graph-side detail
  aggregates

## Open Boundary Note

This plan intentionally separates contract migration from renderer replacement.

If the team later decides to replace the current graph renderer with
`Cytoscape.js` or another framework, that should be recorded as a follow-on
frontend-local plan after the contract and drilldown state model have been
stabilized.
