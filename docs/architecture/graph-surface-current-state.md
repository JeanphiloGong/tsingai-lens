# Graph Surface Current State

## Purpose

This document records the current shared decision for the collection graph
surface and the execution order for the next stabilization wave.

It exists to keep the graph page aligned with the Lens v1 evidence-first,
comparison-first boundary without prematurely turning the graph into a new
primary product surface.

## Current Decision

The current collection graph page remains a secondary derived analytical
surface.

That means:

- the graph page stays available as an advanced view
- it should not define the primary Lens v1 workflow
- evidence and comparison remain the primary collection-facing surfaces
- the current graph implementation should first be stabilized before any new
  product-direction investment

## Product Spec: Relationship Navigation Graph

This section is the shared phase-one specification for the collection graph
surface. It keeps the graph below the research-direction workspace in the
Lens v1 product hierarchy.

### Assumptions

1. The graph page is a web workspace route at `/collections/:id/graph`.
2. The graph remains a secondary analysis surface, not the Lens v1 primary
   acceptance path.
3. The Objective page owns scientific Findings and their Evidence review.
4. The graph page owns relationship navigation, neighborhood exploration, and
   anomaly discovery.
5. The browser should not infer scientific relationships from raw text fields;
   backend projections should provide stable node, edge, link, readiness, and
   warning semantics.

### Objective

Design the collection graph page as a relationship map for asking:

```text
How are papers, evidence, comparisons, materials, process context, measured
properties, and source records connected, and where should I drill down next?
```

The graph should help a researcher:

- see collection structure quickly
- identify dense hubs and isolated nodes
- select one material, property, test condition, comparison, evidence item, or
  document and inspect its relationship neighborhood
- navigate from a node or edge to canonical pages such as document detail,
  evidence review, comparison/result detail, material/objective workspace, or
  source PDF
- notice anomalies such as missing evidence links, overly dense condition
  nodes, truncated graph payloads, unresolved relations, and unsupported
  source traceback
- export GraphML when needed without making export the main experience

The graph is therefore not a final knowledge-conclusion diagram. It is a
relationship navigation and evidence-neighborhood exploration tool.

### Position Relative To Research Direction

The Objective Finding workspace answers:

```text
What does this research Objective support, under which conditions, and can each
Finding be traced to exact Evidence?
```

The graph page answers:

```text
How are the collection objects connected, which relationship should I inspect,
and where are the suspicious or high-value drilldown paths?
```

The graph includes Objective nodes where the projection has stable ownership,
but it remains a navigation/exploration surface rather than replacing the
Finding workspace.

### Current-Stage Object Model

The current graph should stabilize around the existing collection graph
projection:

- `document`
- `objective`
- `evidence`
- `comparison`
- `material`
- `property`
- `test_condition`
- `baseline`

Each node should expose:

- stable `id`
- stable `type`
- short display label
- full label or description for detail panels
- canonical detail links when available
- degree or relationship count
- warning state when the node represents unresolved or low-quality structure

Each edge should expose:

- stable `id`
- `source`
- `target`
- relation type
- weight or confidence when available
- evidence refs or canonical linked records when available
- warning state when the relation is inferred, unresolved, truncated, or lacks
  source support

The graph does not persist its own scientific object model. New node types may
be added only when they project a canonical backend record with stable source
and detail links.

### Backend / Frontend Coordination

Backend responsibilities:

- provide a stable graph projection through the existing same-origin
  `/api/v1/*` contract
- provide node and edge types that are already product-shaped enough for the
  browser to render without semantic guessing
- provide short display labels and preserve full raw labels separately
- provide canonical links or enough stable ids for the frontend to build
  canonical links
- provide edge evidence refs, linked evidence/comparison ids, or explicit
  unavailable states
- provide graph readiness, truncation, stale-state, and warning signals
- provide a neighbors endpoint for progressive expansion
- avoid making the frontend parse long payload text to derive scientific
  meaning

Frontend responsibilities:

- render the graph canvas, filters, search, selection, neighborhood expansion,
  detail panel, and linked-record panel
- keep graph browser requests on the same-origin helper path
- use backend-provided node and edge semantics; do not invent scientific
  relationship meaning in the browser
- use short labels in the canvas and put long labels in the detail panel
- keep canonical pages as the source of detail truth for documents, evidence,
  comparisons, materials, and objectives
- show graph readiness, truncation, stale-state, and warning states explicitly
- verify desktop and mobile interaction with browser screenshots

### Interaction Design

The target layout is:

```text
left:   filters, search, node-type toggles, query controls
center: graph canvas and graph-local toolbar
right:  selected node or edge summary and canonical links
bottom: evidence / comparison / source records related to current selection
```

Required interactions:

- single click node: select, highlight the 1-hop neighborhood, and keep enough
  surrounding context visible
- double click node: expand the node's neighborhood through the backend
  neighbors endpoint
- click edge: show relation type, weight/confidence, source support, and linked
  records
- hover: show lightweight preview only; do not fetch canonical detail
- search: highlight matching visible nodes and allow focusing the first match
- filters: change node visibility without losing the current stable graph
  state unnecessarily
- right-side detail: show summary, type, warnings, and canonical links; do not
  duplicate full canonical pages
- bottom panel: show linked evidence, comparison, and source/document records
  for the current selection
- source links: navigate to document/PDF routes with return path when source
  information exists

### Current Screenshot-Derived Defects

The current graph page is not acceptable until these defects are fixed:

- `Loading graph...` can remain visible at the same time as `Graph loaded`
- overview metric `Themes` can render as `NaN`
- dense theme labels can show long raw test-condition payload text instead of
  readable short labels
- selecting an overview node can over-zoom the canvas and lose relationship
  context
- selected aggregate nodes can fail to populate linked evidence, comparison,
  or document records
- mobile layout can overflow horizontally and places controls before the
  graph canvas, delaying the main visual surface
- Cytoscape style warnings are emitted for unsupported shadow properties
- wheel sensitivity customization emits a runtime warning and should be
  justified or removed

### Commands

Frontend checks:

```bash
cd frontend
npm run check
npm run test:unit -- --run src/routes/_shared/graph.spec.ts
npm run test:e2e -- --reporter=line
npm run build
```

Browser screenshot checks:

```bash
cd frontend
node <playwright-screenshot-script> \
  http://127.0.0.1:5173/collections/<collection_id>/graph
```

Backend checks when graph projection changes:

```bash
cd backend
./.venv/bin/python -m pytest <graph-related-tests> -q
./.venv/bin/python -m ruff check controllers application tests
```

Docs governance check when this document changes:

```bash
python3 scripts/check_docs_governance.py
```

### Project Structure

```text
docs/architecture/graph-surface-current-state.md
  Shared product and architecture boundary for the graph surface.

frontend/src/routes/collections/[id]/graph/+page.svelte
  Graph workspace route implementation.

frontend/src/routes/_shared/graph.ts
  Graph API helpers, projection helpers, labels, filtering, Cytoscape elements,
  linked-record matching, and layout support.

frontend/src/routes/_shared/i18n.ts
  User-facing graph copy.

frontend/src/routes/collections/graph-exploration-interaction-and-layout-proposal.md
  Frontend-local interaction and layout proposal that implements this shared
  boundary.

backend/controllers/ and backend application graph services
  Owning backend graph projection and neighbors endpoints.
```

### Code Style

Frontend display code should separate short canvas labels from full detail
labels:

```ts
const displayLabel = node.short_label ?? truncateGraphLabel(node.label, 48);
const detailLabel = node.label;
```

Selection should preserve context:

```ts
selectNode(nodeId, { focus: 'context' });
```

Backend graph projection should return explicit missing states instead of
forcing the browser to guess:

```python
return GraphNode(
    id=node_id,
    type="test_condition",
    label=short_label,
    raw_label=raw_condition_text,
    links=canonical_links,
    warnings=warnings,
)
```

### Testing Strategy

Unit tests should cover:

- graph metrics never render `NaN`
- long raw labels are converted to short canvas labels while full labels remain
  available for details
- aggregate node selection resolves linked evidence, comparison, and document
  records when backend ids or refs are available
- graph filtering preserves selected state only when the selected node remains
  visible
- unsupported Cytoscape style properties are not emitted

Component/browser tests should cover:

- desktop layout shows controls, canvas, detail panel, and linked panel without
  overlap
- mobile layout shows the graph canvas before advanced controls or provides a
  collapsed controls entry
- single click selects without over-zooming
- double click expands neighbors
- edge selection shows relation details and linked records
- loading, ready, stale, truncated, partial, and error states are distinct
- console has no graph-specific warnings beyond expected dev-server messages

### Boundaries

- Always:
  keep graph secondary to evidence/comparison and research-direction
  workspaces; use same-origin `/api/v1/*`; preserve canonical drilldown links;
  show readiness and warning states; verify with tests and screenshots.
- Ask first:
  changing graph API shape, adding dependencies, replacing Cytoscape, changing
  database schema, making graph primary navigation, or deleting existing
  material/evidence/comparison routes.
- Never:
  present graph paths as final scientific conclusions without evidence
  traceback, parse long raw payload text in the browser as scientific logic,
  hide missing linked evidence behind generic summaries, or introduce a second
  browser API contract.

### Success Criteria

The current-stage graph redesign is acceptable when:

- `/collections/:id/graph` clearly presents itself as a relationship map, not
  the final answer surface
- no ready page shows contradictory loading/loaded states
- overview metrics never show `NaN`
- canvas labels are short and readable; full raw labels remain available in
  details
- selecting a node or edge updates the right detail panel and bottom linked
  records when data exists
- aggregate nodes with linked evidence or comparisons do not show false zeroes
  because of frontend lookup mismatch
- selecting from overview lists does not destroy canvas context through
  excessive zoom
- mobile screenshots show no horizontal overflow and expose the main graph
  surface without excessive scrolling through controls
- GraphML export still works as a secondary action
- console output is free of graph-specific runtime warnings caused by invalid
  Cytoscape style configuration

### Open Questions

- Should the current graph endpoint add explicit `short_label`, `raw_label`,
  `canonical_links`, and `warnings` fields, or should the first repair pass use
  frontend-only display normalization?
- Should objective workspace links appear in the current graph now, or wait
  until the Lens-native objective graph projection is available?
- Should mobile graph controls become a drawer/collapsible panel, or should the
  page reorder canvas before controls?
- Should aggregate node linked-record matching be fixed by backend edge refs,
  frontend matching rules, or both?

## Why The Current Graph Still Feels Misaligned

The current graph page is still useful as a retained GraphRAG artifact browser,
but it does not yet behave like a core Lens research judgment surface.

Current gaps:

- the backend graph payload is still centered on retained graph artifacts
  rather than Lens-native research objects such as claim, evidence,
  condition/context, and comparability
- the current page interaction model is still closer to graph inspection and
  debugging than to evidence-backed research judgment
- the frontend graph page had contract drift against the hardened backend
  payload and error model
- layout and detail behavior still need basic stabilization before bigger
  product bets are made

## Near-Term Execution Order

The next implementation wave should stay narrow:

1. fix frontend and backend graph contract mismatch
2. fix frontend handling of stable backend graph error codes
3. fix current graph page usability issues as a secondary surface
4. revisit the product decision only after the current page is stable enough
   to evaluate honestly

This wave is intentionally about stabilization, not repositioning.

## Explicit Non-Goals For This Wave

Do not do the following in the current bug-fix pass:

- do not switch the graph rendering framework yet
- do not redefine the graph page as the main Lens v1 interface
- do not rebuild the graph around evidence/comparison-derived objects yet
- do not treat the retained GraphRAG graph as proof of final product fit

## Deferred Product Decision

After the current graph page is stabilized, the product team should make an
explicit decision between two directions:

- continue treating graph as a GraphRAG-oriented advanced surface
- design a stronger Lens-native graph derived from evidence cards,
  comparison rows, and document profiles

That later decision should be made as a product and architecture choice, not
hidden inside small UI or backend cleanup work.

## Decision Rule For Revisit

Revisit the graph product direction when the current page is no longer blocked
by basic contract drift or surface bugs and the team is ready to evaluate one
of these questions directly:

- should graph remain a secondary inspection view only
- should graph become a first-class research judgment surface
- if it becomes first-class, should its object model be GraphRAG-native or
  Lens-native

## Related Docs

- [System Overview](../overview/system-overview.md)
- [Lens V1 Architecture Boundary](lens-v1-architecture-boundary.md)
- [Lens V1 Definition](../contracts/lens-v1-definition.md)
- [Lens V1 Frontend Interface Spec](../../frontend/src/routes/collections/lens-v1-interface-spec.md)
