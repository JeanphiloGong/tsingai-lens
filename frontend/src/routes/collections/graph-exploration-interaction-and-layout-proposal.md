# Graph Exploration Interaction And Layout Proposal

## Summary

This document records a frontend-local follow-on proposal for improving the
collection graph exploration experience after the Cytoscape cutover.

The proposal keeps the current lean graph contract and canonical drilldown
routes, but upgrades the graph page interaction model so users can focus a
node, expand neighborhoods directly from the canvas, and read more meaningful
labels inside non-overlapping graph nodes.

## Context

The current graph page is already on the right contract seam:

- the browser reads lean structure data from `/graph`
- neighborhood expansion stays graph-owned through `/graph/nodes/{node_id}/neighbors`
- canonical detail still comes from document, evidence, and comparison routes
- layout runs in the browser with Cytoscape and incremental `fcose`

That cutover fixed the data seam, but the interaction seam is still too thin
for real graph exploration:

- single click selects a node, but does not move the viewport toward it
- neighborhood expansion still depends on the side-panel button rather than a
  direct graph interaction
- nodes mostly behave like points with labels, not readable graph cards
- all node kinds are rendered with the same label strategy even though
  aggregate hubs and detail nodes have different jobs

The result is a graph that is technically functional, but still feels more
like a preview canvas than a graph exploration surface.

## Scope

In scope:

- graph-canvas interaction rules for selection, focus, and expansion
- node label placement and node-size strategy
- non-overlap and incremental layout expectations
- node-kind-specific display rules for aggregate hubs versus detail nodes
- direct canvas actions that stay consistent with the existing canonical
  drilldown model

Out of scope:

- changing the graph route path or graph API contract
- moving detail ownership back into the graph payload
- introducing a second browser contract or compatibility layer
- making graph the primary Lens v1 acceptance surface
- replacing Cytoscape with another renderer in the same wave

## Proposed Change

### 0. Reframe The Page As Graph Navigation Plus Evidence Review

The first product-facing pass should organize the existing lean graph contract
into a research review workspace without changing the backend graph API.

The page should use:

- a left filter panel for node visibility, search, and graph query controls
- the central Cytoscape canvas as the relationship navigation surface
- a right insight panel for the selected node or edge
- a bottom evidence panel that lists comparison rows connected to the current
  selection when those rows can be resolved from existing canonical endpoints

This is intentionally a frontend information-architecture improvement. It does
not yet claim that the backend graph can express stable process-to-property or
mechanism relationships. Those require a later Lens-native graph projection
that adds process nodes and relation-level evidence aggregation.

### 1. Treat Single Click As Selection Plus Focus

Single click on a node should:

- select the node
- open the current right-side detail behavior
- smoothly center the viewport on the node
- highlight the selected node, its 1-hop neighbors, and the connecting edges

This should become the primary graph exploration action because it is
discoverable and works well on desktop and trackpad workflows.

### 2. Treat Double Click As Direct Neighborhood Expansion

Double click on a node should:

- call the existing neighbors endpoint
- merge the returned nodes and edges into the local graph state
- keep the clicked node centered after expansion
- preserve existing node positions and only lay out the new neighborhood slice

This makes graph expansion feel like exploration rather than panel-driven
configuration.

### 3. Keep Right Click As A Secondary Power Path

Right click should not be the only expansion path.

If added, it should open a compact context menu with graph-local actions such
as:

- expand neighborhood
- open detail target
- open source document or filtered comparisons

This is useful for advanced users, but it should remain secondary because
right-click behavior is weaker on trackpads, touch devices, and accessibility
flows.

### 4. Add Lightweight Hover Feedback

Hover should stay informational rather than destructive.

Hover on a node should:

- temporarily highlight the node and adjacent edges
- show a small preview with label, node kind, and degree
- avoid firing canonical detail fetches

This keeps the graph readable without overloading the network or turning
movement into a cascade of panel changes.

### 5. Put Text Inside Nodes, But Not Uniformly

The graph should stop treating every node as a tiny dot with external text.

Instead:

- aggregate hubs such as `material`, `property`, `test_condition`, and
  `baseline` should render as card-like nodes with text inside the node body
- document, evidence, and comparison nodes should stay more compact and show a
  short internal label or a truncated title
- long values should wrap to one or two lines and then truncate

This keeps graph hubs legible while avoiding the visual collapse that happens
when every detail node tries to render full text.

### 6. Size Nodes From Their Text Role

Node size should become content-aware instead of degree-only.

Recommended rule:

- aggregate nodes grow to fit wrapped internal text
- detail nodes stay within a tighter size range
- degree can still affect emphasis, but should not overpower readability

This makes the graph feel like a readable semantic surface rather than a pure
network diagram.

### 7. Keep Automatic Layout, But Prevent Overlap Aggressively

The graph should continue using Cytoscape `fcose`, but with stronger
anti-overlap expectations:

- node dimensions should feed into layout inputs
- node repulsion and ideal edge length should be tuned for card-style nodes
- incremental expansion should continue to pin existing nodes and place only
  the newly added slice
- blank-space double click should reset the viewport to a sensible fit-all view

This preserves the good part of the current Cytoscape migration while making
the graph easier to read after text moves into nodes.

## File Change Plan

Primary files:

- `frontend/src/routes/collections/[id]/graph/+page.svelte`
- `frontend/src/routes/_shared/i18n.ts`
- `frontend/src/routes/layout.css` or the graph page local style block,
  depending on whether the visual rules remain graph-local

Expected changes:

- add viewport focus behavior on node selection
- add double-click neighborhood expansion behavior
- optionally add context-menu handling for graph-local actions
- distinguish hover, selected, connected, and expanded visual states
- move aggregate-node text into the node body
- compute node size from node kind plus text length
- retune layout inputs for non-overlapping card nodes
- add copy for interaction hints and any new graph actions

## Verification

Required verification after implementation:

- single click selects a node and recenters the viewport
- double click expands the selected node neighborhood without re-laying out the
  whole graph
- aggregate nodes remain readable with text inside the node
- detail nodes stay compact and do not flood the canvas with long labels
- expanded neighborhoods do not visibly collapse into heavy overlap
- graph detail, document links, and filtered-comparison drilldown still work
- touchpad and standard mouse flows both retain a usable main action path even
  if right click is unavailable

## Risks

- if too much text is pushed into every node kind, the graph will become less
  readable instead of more readable
- double-click timing can conflict with single-click detail loading if the
  interaction is not debounced carefully
- context menus can create accessibility and cross-platform inconsistency if
  they become the primary action path
- stronger anti-overlap layout settings can make large graphs slower if the
  tuning is too aggressive

## Related Docs

- [`core-derived-graph-structure-and-drilldown-frontend-alignment-plan.md`](core-derived-graph-structure-and-drilldown-frontend-alignment-plan.md)
  Lean graph contract and canonical drilldown frontend cutover plan
- [`lens-v1-interface-spec.md`](lens-v1-interface-spec.md)
  Collection route-family interface authority that keeps graph secondary
- [`../../docs/frontend-plan.md`](../../docs/frontend-plan.md)
  Frontend same-origin contract and graph integration notes
